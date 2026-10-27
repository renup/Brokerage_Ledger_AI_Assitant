from typing import Literal

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ledger_core.auth import get_current_customer
from ledger_core.database import get_session
from ledger_core.models import Account, Customer, LinkedBank, Withdrawal
from ledger_core.schemas import WithdrawalPublic

router = APIRouter(prefix="/me/withdrawals", tags=["withdrawals"])


# Full path: GET /me/withdrawals, optionally ?status=pending
@router.get("", response_model=list[WithdrawalPublic])
def my_withdrawals(
    # A query parameter. Literal[...] limits it to these values;
    # anything else gets an automatic 422. Defaults to "all" when not given.
    status: Literal["pending", "completed", "failed", "all"] = "all",
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
