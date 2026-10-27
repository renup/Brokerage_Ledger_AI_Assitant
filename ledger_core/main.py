from fastapi import Depends, FastAPI, HTTPException
from sqlmodel import Session, select

from ledger_core.auth import create_access_token, get_current_customer, verify_password
from ledger_core.config import settings
from ledger_core.database import get_session
from ledger_core.models import Customer
from ledger_core.schemas import CustomerPublic, LoginRequest, TokenResponse

# The app. The title shows at the top of the /docs page.
app = FastAPI(title="ledger-core")


# A cheap way for people and tools to ask "is the service up?"
@app.get("/health")
def health():
    # A Python dict that FastAPI turns into JSON
    return {"status": "ok"}


# response_model sets the shape of the answer (and shows it in /docs)
@app.post("/auth/login", response_model=TokenResponse)
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


# Depends(get_current_customer) is what protects this endpoint.
# response_model=CustomerPublic returns only id, name and email, never the hash.
@app.get("/me", response_model=CustomerPublic)
def me(customer: Customer = Depends(get_current_customer)):
    return customer
