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