from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import update, func
from sqlmodel import Session, select

from ledger_core.auth import get_current_customer
from ledger_core.database import get_session
from ledger_core.models import Account, Customer, LinkedBank, Withdrawal
from ledger_core.schemas import CancelWithdrawalResponse, WithdrawalPublic, WithdrawalEligibilityPublic
from ledger_core.withdrawal_rules import (
    available_to_withdraw_cents,
    cash_balance_after_withdrawal_cents,
    find_reasons_withdrawal_is_blocked,
)

router = APIRouter(prefix="/me/withdrawals", tags=["withdrawals"])


# Finds ONE withdrawal, but only if it belongs to this customer. Anything else is a 404.
# (Same idea as verify_transfer_ownership: someone else's id looks identical to one that doesn't exist.)
def verify_withdrawal_ownership(withdrawal_id: int, customer: Customer, session: Session) -> Withdrawal:
    withdrawal = session.exec(
        select(Withdrawal)
        # A withdrawal has no customer_id, so we reach the owner through its account
        .join(Account, Withdrawal.account_id == Account.id)
        # Both conditions must hold: the right id AND the right owner
        .where(Withdrawal.id == withdrawal_id, Account.customer_id == customer.id)
    ).first()
    if withdrawal is None:
        raise HTTPException(status_code=404, detail="Withdrawal not found")
    return withdrawal


# Full path: GET /me/withdrawals, optionally ?status=pending
@router.get("", response_model=list[WithdrawalPublic])
def my_withdrawals(
    # A query parameter. Literal[...] limits it to these values;
    # anything else gets an automatic 422. Defaults to "all" when not given.
    status: Literal["pending", "completed", "failed", "cancelled", "all"] = "all",
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
):
    query = (
        # We want two tables' columns at once: the withdrawal and its bank
        select(Withdrawal, LinkedBank)
        .select_from(Withdrawal)
        # A withdrawal has no customer_id, so we reach the owner through its account:
        # withdrawals -> accounts -> customer
        .join(Account, Withdrawal.account_id == Account.id)
        # Join the bank so we can show its name instead of just bank_id
        .join(LinkedBank, Withdrawal.bank_id == LinkedBank.id)
        # The ownership filter: only this customer's accounts
        .where(Account.customer_id == customer.id)
        # Newest first
        .order_by(Withdrawal.created_at.desc())
    )
    # Only narrow by status when the caller asked for a specific one
    if status != "all":
        query = query.where(Withdrawal.status == status)
    # Each row is a (withdrawal, bank) pair
    rows = session.exec(query).all()
    # One WithdrawalPublic per row, returned as one list. An empty result gives [].
    return [
        WithdrawalPublic(
            id=w.id,
            amount=w.amount_cents / 100,
            bank=b.bank_name,
            status=w.status,
            created_at=w.created_at,
            expected_by=w.expected_by,
            business_day=w.business_day,
            total_days=w.total_days,
        )
        for w, b in rows
    ]

# POST, because it changes something on the server
@router.post("/{withdrawal_id}/cancel", response_model=CancelWithdrawalResponse)
def cancel_pending_withdrawal(
    withdrawal_id: int,
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
):
    # Ownership check first: someone else's withdrawal is a 404
    verify_withdrawal_ownership(withdrawal_id, customer, session)

    # Change it ONLY IF it is still pending, in one statement (a compare-and-set). If the
    # withdrawal completed a moment ago, no row matches and nothing is changed.
    rows_changed = session.exec(
        update(Withdrawal)
        .where(Withdrawal.id == withdrawal_id, Withdrawal.status == "pending")
        .values(status="cancelled")
    ).rowcount
    session.commit()

    # 409 Conflict = "the request is fine, but it doesn't fit the current state"
    if rows_changed != 1:
        raise HTTPException(status_code=409, detail="Only pending withdrawals can be cancelled")
    return CancelWithdrawalResponse(id=withdrawal_id, status="cancelled")


# Full path: GET /me/withdrawals/eligibility?amount=500&account_type=roth_ira
# Answers "could I withdraw this amount right now?" without changing anything. One result per account
# (or just the one asked about), so a customer with two accounts sees both.
@router.get("/eligibility", response_model=list[WithdrawalEligibilityPublic])
def check_withdrawal_eligibility(
    # Dollars, as the customer says it. gt=0 rejects zero and negatives with an automatic 422.
    amount: float = Query(gt=0, le=1_000_000),
    account_type: Literal["individual", "roth_ira", "traditional_ira"] | None = None,
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
):
    # round(), because 19.99 * 100 is 1998.9999999999998 in floating point
    amount_cents = round(amount * 100)

    # Only this customer's own accounts, optionally narrowed to one type
    query = select(Account).where(Account.customer_id == customer.id)
    if account_type is not None:
        query = query.where(Account.type == account_type)

    results = []
    for account in session.exec(query).all():
        # How much pending withdrawals already claim from this account (0 when there are none)
        pending_cents = session.exec(
            select(func.coalesce(func.sum(Withdrawal.amount_cents), 0)).where(
                Withdrawal.account_id == account.id, Withdrawal.status == "pending"
            )
        ).one()
        reasons = find_reasons_withdrawal_is_blocked(account, pending_cents, amount_cents)
        results.append(
            WithdrawalEligibilityPublic(
                account_type=account.type,
                number_last4=account.number_last4,
                eligible=not reasons,
                available_to_withdraw=available_to_withdraw_cents(account, pending_cents) / 100,
                # The balance as it stands, and what it would be after this withdrawal (only if it is allowed)
                cash_balance=account.cash_balance_cents / 100,
                cash_balance_after=None if reasons else cash_balance_after_withdrawal_cents(account, amount_cents) / 100,
                reasons=reasons,
            )
        )
    return results
