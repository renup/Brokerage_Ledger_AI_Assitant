from fastapi import APIRouter, Depends
from sqlmodel import Session

from ledger_core.auth import get_current_customer
from ledger_core.database import get_session
from ledger_core.models import Customer
from ledger_core.schemas import CustomerPublic, ProfilePublic, ProfileUpdate

# The logged-in customer's own profile
router = APIRouter(prefix="/me", tags=["me"])


# Full path: GET /me (the path is "" because the prefix already says "/me").
# Depends(get_current_customer) is what protects this endpoint.
# response_model=CustomerPublic returns only id, name and email, never the hash.
@router.get("", response_model=CustomerPublic)
def me(customer: Customer = Depends(get_current_customer)):
    return customer

@router.patch("/profile", response_model=ProfilePublic)
def update_profile(
    body: ProfileUpdate,
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session)
):
    customer.legal_name = body.legal_name
    session.add(customer)
    session.commit()
    session.refresh(customer)
    return customer