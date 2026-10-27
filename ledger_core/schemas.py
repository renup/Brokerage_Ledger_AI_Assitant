from pydantic import BaseModel
from datetime import datetime

# Schemas describe the shape of data going in and out of the API.
# They are not database tables (that's models.py).


# What the caller sends to /auth/login. A missing field gives an automatic 422 error.
class LoginRequest(BaseModel):
    email: str
    password: str


# What /auth/login sends back
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # default, so we don't have to set it each time
    expires_in: int  # seconds until the token expires


# Only these three fields are ever returned for a customer.
# Using this as a response_model is how we make sure password_hash never leaks.
class CustomerPublic(BaseModel):
    id: int
    name: str
    email: str

# One account as the caller sees it. The database stores cents;
# we convert to dollars here at the edge (cash_balance_cents / 100).
class AccountPublic(BaseModel):
    id: int
    type: str
    number_last4: str
    cash_balance: float  # dollars, e.g. 3250.75
    status: str


# One withdrawal as the caller sees it.
# "bank" is the bank's name, looked up from linked_banks (a join, see routers/withdrawals.py).
class WithdrawalPublic(BaseModel):
    id: int
    amount: float  # dollars
    bank: str
    status: str
    created_at: datetime
    expected_by: datetime
    business_day: int  # "day 2 of 3" = business_day 2, total_days 3
    total_days: int

# One transfer in a list
class TransferPublic(BaseModel):
    id: int
    direction: str  # "in" or "out"
    other_broker: str
    account_type: str
    status: str
    error_code: str | None  # None for transfers that haven't failed
    created_at: datetime
    expected_by: datetime


# The detail view = everything in TransferPublic, plus error_message.
# Putting a class name in brackets means "inherit": it gets all the fields above,
# and we only write the new one.
class TransferDetail(TransferPublic):
    error_message: str | None


# What the retry endpoint answers with
class RetryResponse(BaseModel):
    id: int
    status: str