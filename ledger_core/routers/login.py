from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ledger_core.auth import create_access_token, verify_password
from ledger_core.config import settings
from ledger_core.database import get_session
from ledger_core.models import Customer
from ledger_core.schemas import LoginRequest, TokenResponse

# A router is a mini-app that groups related endpoints. main.py plugs it in.
# prefix is added to every path below; tags group the endpoints in /docs.
router = APIRouter(prefix="/auth", tags=["auth"])


# Full path: POST /auth/login ("/auth" prefix + "/login").
# response_model sets the shape of the answer (and shows it in /docs).
@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, session: Session = Depends(get_session)):
    # SELECT * FROM customers WHERE email = ... LIMIT 1. Gives None if no match.
    customer = session.exec(select(Customer).where(Customer.email == body.email)).first()
    # Same error whether the email is unknown or the password is wrong,
    # so nobody can discover which emails are registered.
    if customer is None or not verify_password(body.password, customer.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return TokenResponse(
        access_token=create_access_token(customer.id),
        # minutes * 60 = seconds (3600 for a 60-minute token)
        expires_in=settings.token_expire_minutes * 60,
    )
