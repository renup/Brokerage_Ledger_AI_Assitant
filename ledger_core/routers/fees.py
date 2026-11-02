from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ledger_core.auth import get_current_customer
from ledger_core.database import get_session
from ledger_core.models import Account, Customer, FeeSchedule
from ledger_core.schemas import FeePublic

router = APIRouter(prefix="/me/fees", tags=["fees"])


# Full path: GET /me/fees
@router.get("", response_model=list[FeePublic])
def my_fees(
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
):
    # The account types this customer holds, e.g. ["individual", "roth_ira"]
    held = session.exec(select(Account.type).where(Account.customer_id == customer.id)).all()
    fees = session.exec(
        select(FeeSchedule)
        # Fees for the types they hold, plus the ones that apply to everybody
        .where(FeeSchedule.account_type.in_([*held, "all"]))
        .order_by(FeeSchedule.account_type, FeeSchedule.name)
    ).all()
    # Build the API shape (FeePublic), not the table class (FeeSchedule)
    return [
        FeePublic(
            name=f.name,
            # Cents in the database, dollars in the API
            amount=f.amount_cents / 100,
            frequency=f.frequency,
            applies_to=f.account_type,
            description=f.description,
        )
        for f in fees
    ]
