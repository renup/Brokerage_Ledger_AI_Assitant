from fastapi import APIRouter, Depends

from ledger_core.auth import get_current_customer
from ledger_core.models import Customer
from ledger_core.schemas import CustomerPublic

# The logged-in customer's own profile
router = APIRouter(prefix="/me", tags=["me"])


# Full path: GET /me (the path is "" because the prefix already says "/me").
# Depends(get_current_customer) is what protects this endpoint.
# response_model=CustomerPublic returns only id, name and email, never the hash.
@router.get("", response_model=CustomerPublic)
def me(customer: Customer = Depends(get_current_customer)):
    return customer
