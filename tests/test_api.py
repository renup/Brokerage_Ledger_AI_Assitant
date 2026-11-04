from tests.helpers import login_headers

MAYA = "maya.patel@example.com"
RENU = "renu.punjabi@example.com"


# Each test takes "client" as a parameter, so pytest supplies the fixture from conftest.py
def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login_success(client):
    response = client.post("/auth/login", json={"email": MAYA, "password": "demo1234"})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["access_token"]  # not empty


def test_login_wrong_password(client):
    response = client.post("/auth/login", json={"email": MAYA, "password": "wrong"})
    assert response.status_code == 401


def test_missing_token_is_rejected(client):
    # Every protected endpoint must say 401 when no token is sent
    for path in ["/me", "/me/accounts", "/me/withdrawals", "/me/transfers"]:
        assert client.get(path).status_code == 401


def test_me_never_returns_password_hash(client):
    response = client.get("/me", headers=login_headers(client, MAYA))
    assert response.status_code == 200
    assert response.json()["name"] == "Maya Patel"
    assert "password_hash" not in response.json()


def test_maya_sees_her_pending_withdrawal(client):
    headers = login_headers(client, MAYA)
    response = client.get("/me/withdrawals?status=pending", headers=headers)
    assert response.status_code == 200
    withdrawals = response.json()
    assert len(withdrawals) == 1
    assert withdrawals[0]["amount"] == 1200.0
    assert withdrawals[0]["bank"] == "Chase"
    # "day 2 of 3"
    assert (withdrawals[0]["business_day"], withdrawals[0]["total_days"]) == (2, 3)


# The sheet's key security test: one customer must not be able to read another's data
def test_maya_cannot_read_renus_transfer(client):
    # Find Renu's transfer id by logging in as Renu...
    renu_transfer_id = client.get("/me/transfers", headers=login_headers(client, RENU)).json()[0]["id"]
    # ...then try to open it with Maya's token. 404, not 403, so its existence isn't revealed.
    response = client.get(f"/me/transfers/{renu_transfer_id}", headers=login_headers(client, MAYA))
    assert response.status_code == 404


def test_maya_cannot_see_renus_data_in_lists(client):
    maya_accounts = client.get("/me/accounts", headers=login_headers(client, MAYA)).json()
    # Only Maya's two accounts, identified by their last four digits
    assert {a["number_last4"] for a in maya_accounts} == {"4821", "7730"}


def test_retry_changes_status(client):
    headers = login_headers(client, MAYA)
    transfer = client.get("/me/transfers?status=failed", headers=headers).json()[0]
    assert transfer["error_code"] == "214"

    response = client.post(f"/me/transfers/{transfer['id']}/retry", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "requested"

    # A second retry is refused, because the transfer is no longer failed
    assert client.post(f"/me/transfers/{transfer['id']}/retry", headers=headers).status_code == 409


def test_cannot_retry_someone_elses_transfer(client):
    maya_transfer_id = client.get("/me/transfers", headers=login_headers(client, MAYA)).json()[0]["id"]
    response = client.post(f"/me/transfers/{maya_transfer_id}/retry", headers=login_headers(client, RENU))
    assert response.status_code == 404


def test_update_legal_name(client):
    headers = login_headers(client, MAYA)
    response = client.patch("/me/profile", json={"legal_name": "  Maya Rose Patel  "}, headers=headers)
    assert response.status_code == 200
    # Spaces around the name were trimmed
    assert response.json()["legal_name"] == "Maya Rose Patel"
    # A blank name is rejected
    assert client.patch("/me/profile", json={"legal_name": "   "}, headers=headers).status_code == 422

def test_maya_sees_fees_for_her_account_types_only(client):
    fees = client.get("/me/fees", headers=login_headers(client, MAYA)).json()
    # Maya holds an individual and a Roth IRA: the shared fees plus the Roth one, never the traditional IRA row
    assert {f["applies_to"] for f in fees} == {"all", "roth_ira"}
    assert any(f["name"] == "Outgoing account transfer" and f["amount"] == 75.0 for f in fees)


def test_individual_only_customer_sees_no_ira_fee(client):
    fees = client.get("/me/fees", headers=login_headers(client, RENU)).json()
    assert {f["applies_to"] for f in fees} == {"all"}


def test_maya_sees_only_her_tax_documents(client):
    documents = client.get("/me/tax-documents", headers=login_headers(client, MAYA)).json()
    assert len(documents) == 4
    assert {d["number_last4"] for d in documents} == {"4821", "7730"}


def test_tax_documents_can_be_filtered_by_year(client):
    documents = client.get("/me/tax-documents?year=2026", headers=login_headers(client, MAYA)).json()
    assert len(documents) == 1
    # A form that is not issued yet has no download link
    assert documents[0]["status"] == "pending" and documents[0]["download_path"] is None


def test_fees_and_tax_documents_need_a_token(client):
    assert client.get("/me/fees").status_code == 401
    assert client.get("/me/tax-documents").status_code == 401


# The id of a customer's first withdrawal with the given status, found through the API itself
def withdrawal_id_with_status(client, headers, status):
    return client.get(f"/me/withdrawals?status={status}", headers=headers).json()[0]["id"]


def test_cancelling_a_pending_withdrawal_marks_it_cancelled(client):
    headers = login_headers(client, MAYA)
    withdrawal_id = withdrawal_id_with_status(client, headers, "pending")
    response = client.post(f"/me/withdrawals/{withdrawal_id}/cancel", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"id": withdrawal_id, "status": "cancelled"}
    # It no longer counts as pending, and can be found under "cancelled"
    assert client.get("/me/withdrawals?status=pending", headers=headers).json() == []
    assert [w["id"] for w in client.get("/me/withdrawals?status=cancelled", headers=headers).json()] == [withdrawal_id]


def test_cancelling_twice_gives_409(client):
    headers = login_headers(client, MAYA)
    withdrawal_id = withdrawal_id_with_status(client, headers, "pending")
    assert client.post(f"/me/withdrawals/{withdrawal_id}/cancel", headers=headers).status_code == 200
    assert client.post(f"/me/withdrawals/{withdrawal_id}/cancel", headers=headers).status_code == 409


def test_a_completed_withdrawal_cannot_be_cancelled(client):
    headers = login_headers(client, RENU)
    withdrawal_id = withdrawal_id_with_status(client, headers, "completed")
    assert client.post(f"/me/withdrawals/{withdrawal_id}/cancel", headers=headers).status_code == 409
    # And it is unchanged
    assert client.get("/me/withdrawals?status=completed", headers=headers).json()[0]["id"] == withdrawal_id


def test_cannot_cancel_someone_elses_withdrawal_or_a_missing_one(client):
    maya_headers = login_headers(client, MAYA)
    mayas_id = withdrawal_id_with_status(client, maya_headers, "pending")
    # Renu tries to cancel Maya's withdrawal: 404, the same as an id that does not exist
    renu_headers = login_headers(client, RENU)
    assert client.post(f"/me/withdrawals/{mayas_id}/cancel", headers=renu_headers).status_code == 404
    assert client.post("/me/withdrawals/99999/cancel", headers=maya_headers).status_code == 404
    # Maya's is still pending
    assert withdrawal_id_with_status(client, maya_headers, "pending") == mayas_id


def test_cancel_needs_a_token(client):
    assert client.post("/me/withdrawals/1/cancel").status_code == 401
