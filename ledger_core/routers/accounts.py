from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ledger_core.auth import get_current_customer
from ledger_core.database import get_session
from ledger_core.models import Account, Customer
from ledger_core.schemas import AccountPublic

router = APIRouter(prefix="/me/accounts", tags=["accounts"])


# Full path: GET /me/accounts.
# list[AccountPublic] = the answer is a list, each item shaped like AccountPublic.
@router.get("", response_model=list[AccountPublic])
def my_accounts(
    # The customer comes from the token, not from the URL,
    # so a caller can never ask for someone else's accounts.
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
):
    # SELECT * FROM accounts WHERE customer_id = <the logged-in customer>
    accounts = session.exec(select(Account).where(Account.customer_id == customer.id)).all()
    # Build one AccountPublic for EVERY account, then return the whole list once.
    # (A return inside a for-loop would stop after the first account.)
    return [
        AccountPublic(
            id=a.id,
            type=a.type,
            number_last4=a.number_last4,
            # The database stores cents; the API shows dollars
            cash_balance=a.cash_balance_cents / 100,
            status=a.status,
        )
        for a in accounts
    ]
