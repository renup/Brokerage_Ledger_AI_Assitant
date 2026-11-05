from types import SimpleNamespace

from ledger_core.withdrawal_rules import (
    MAX_SINGLE_WITHDRAWAL_CENTS,
    available_to_withdraw_cents,
    find_reasons_withdrawal_is_blocked,
)
from tests.helpers import login_headers


# A stand-in account: the rules only read balance and status, so no database is needed
def account(cash_cents=100_000, status="active"):
    return SimpleNamespace(cash_balance_cents=cash_cents, status=status)


# ---- the rules on their own ----

def test_a_withdrawal_within_the_balance_has_no_blocking_reasons():
    assert find_reasons_withdrawal_is_blocked(account(), 0, 50_000) == []


def test_pending_withdrawals_reduce_what_is_available():
    assert available_to_withdraw_cents(account(100_000), 30_000) == 70_000
    reasons = find_reasons_withdrawal_is_blocked(account(100_000), 30_000, 80_000)
    assert reasons == ["Only $700.00 is available after pending withdrawals."]


def test_available_cash_is_never_negative():
    assert available_to_withdraw_cents(account(10_000), 50_000) == 0


def test_a_restricted_account_is_blocked():
    reasons = find_reasons_withdrawal_is_blocked(account(status="restricted"), 0, 100)
    assert reasons == ["The account is restricted."]


def test_the_single_withdrawal_limit_is_enforced():
    rich = account(MAX_SINGLE_WITHDRAWAL_CENTS * 2)
    assert find_reasons_withdrawal_is_blocked(rich, 0, MAX_SINGLE_WITHDRAWAL_CENTS) == []
    assert len(find_reasons_withdrawal_is_blocked(rich, 0, MAX_SINGLE_WITHDRAWAL_CENTS + 1)) == 1


def test_every_broken_rule_is_reported():
    reasons = find_reasons_withdrawal_is_blocked(account(100, "restricted"), 0, MAX_SINGLE_WITHDRAWAL_CENTS + 1)
    assert len(reasons) == 3


# ---- the endpoint ----

MAYA = "maya.patel@example.com"


def test_maya_gets_one_result_per_account(client):
    headers = login_headers(client, MAYA)
    results = client.get("/me/withdrawals/eligibility?amount=100", headers=headers).json()
    assert {r["account_type"] for r in results} == {"individual", "roth_ira"}
    assert all(r["eligible"] for r in results)


def test_pending_withdrawal_is_subtracted_from_mayas_individual_account(client):
    headers = login_headers(client, MAYA)
    results = client.get("/me/withdrawals/eligibility?amount=100&account_type=individual", headers=headers).json()
    # $3,250.75 balance minus her $1,200.00 pending withdrawal
    assert [r["available_to_withdraw"] for r in results] == [2050.75]


def test_amount_above_available_is_not_eligible(client):
    headers = login_headers(client, MAYA)
    results = client.get("/me/withdrawals/eligibility?amount=3000&account_type=individual", headers=headers).json()
    assert results[0]["eligible"] is False
    assert "available" in results[0]["reasons"][0]


def test_restricted_account_is_not_eligible(client):
    headers = login_headers(client, "david.kim@example.com")
    results = client.get("/me/withdrawals/eligibility?amount=10", headers=headers).json()
    assert results[0]["eligible"] is False
    assert results[0]["reasons"] == ["The account is restricted."]


def test_zero_negative_and_unknown_account_type_are_rejected(client):
    headers = login_headers(client, MAYA)
    assert client.get("/me/withdrawals/eligibility?amount=0", headers=headers).status_code == 422
    assert client.get("/me/withdrawals/eligibility?amount=-5", headers=headers).status_code == 422
    assert client.get("/me/withdrawals/eligibility?amount=5&account_type=crypto", headers=headers).status_code == 422


def test_eligibility_needs_a_token(client):
    assert client.get("/me/withdrawals/eligibility?amount=5").status_code == 401
