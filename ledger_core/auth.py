from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from ledger_core.config import settings
from ledger_core.database import get_session
from ledger_core.models import Customer

# Reads the "Authorization: Bearer <token>" header from a request.
# auto_error=False gives us None when it's missing, so we can return our own 401.
bearer_scheme = HTTPBearer(auto_error=False)


def verify_password(password: str, password_hash: str) -> bool:
    # bcrypt hashes the typed password using the salt stored inside the saved hash
    # and compares the results. Hashes can't be reversed, only compared.
    # .encode() turns text into bytes, which bcrypt needs.
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(customer_id: int) -> str:
    # The token stops being valid this many minutes from now
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.token_expire_minutes)
    # "sub" (subject) = who the token is for. The JWT standard wants it as a string.
    # "exp" = expiry time, which the library checks for us when decoding.
    payload = {"sub": str(customer_id), "exp": expires}
    # Sign the payload with our secret. Anyone can read a JWT, but nobody can
    # change it without the secret.
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# A "dependency": endpoints list this as a parameter and FastAPI runs it first.
# Any endpoint that uses it is automatically protected, and gets the logged-in customer.
def get_current_customer(
    # FastAPI fills these in by running bearer_scheme and get_session first
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> Customer:
    # One error reused for every failure, so callers can't tell what went wrong.
    # 401 = "not authenticated". The header is the standard hint that a Bearer token is expected.
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # No Authorization header at all
    if credentials is None:
        raise unauthorized
    try:
        # Checks the signature and the expiry, then returns the payload.
        # algorithms=[...] is the only one we accept (blocks a trick where an
        # attacker picks a weaker one). "require" rejects tokens missing exp or sub.
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        # Covers a bad signature, an expired token, or garbage text
        raise unauthorized
    # Look the customer up by primary key. If they were deleted after the token
    # was issued, reject it.
    customer = session.get(Customer, int(payload["sub"]))
    if customer is None:
        raise unauthorized
    return customer
