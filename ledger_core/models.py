from datetime import datetime, timezone

from sqlmodel import SQLModel, Field


# Each class below is one database table. table=True is what makes it a real table.
# Tables that others point to come first (Customer, Account, LinkedBank, ...).
class Customer(SQLModel, table=True):
    __tablename__ = "customers"

    # None until saved. The database assigns 1, 2, 3... itself.
    id: int | None = Field(default=None, primary_key=True)
    name: str
    # The official name on file. A mismatch with another broker's record is what
    # makes Maya's transfer fail.
    legal_name: str
    # unique=True: the database rejects a second customer with the same email
    email: str = Field(unique=True)
    # We store a bcrypt hash, never the real password
    password_hash: str
    # A function (not a value) so each row gets its own timestamp.
    # Timezone-aware (UTC), because SQLModel refuses naive datetimes.
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Account(SQLModel, table=True):
    __tablename__ = "accounts"

    id: int | None = Field(default=None, primary_key=True)
    # Foreign key: must match an id in customers, so an account always has a real owner
    customer_id: int = Field(foreign_key="customers.id")
    # individual, roth_ira or traditional_ira
    type: str
    # str, not int, so a value like "0042" keeps its leading zero
    number_last4: str
    # Money is whole cents (840000 = $8,400.00) so decimals can't drift
    cash_balance_cents: int
    status: str


# A bank account the customer has connected, e.g. Maya's Chase account
class LinkedBank(SQLModel, table=True):
    __tablename__ = "linked_banks"

    id: int | None = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customers.id")
    bank_name: str
    last4: str


# Money moving from a brokerage account out to a linked bank
class Withdrawal(SQLModel, table=True):
    __tablename__ = "withdrawals"

    id: int | None = Field(default=None, primary_key=True)
    # Where the money comes from
    account_id: int = Field(foreign_key="accounts.id")
    # Where it goes
    bank_id: int = Field(foreign_key="linked_banks.id")
    amount_cents: int
    # pending, completed or failed
    status: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # When the money should arrive
    expected_by: datetime
    # Progress as "day 2 of 3"
    business_day: int
    total_days: int


# Assets moving between brokerages, e.g. Maya's IRA transfer from Fidelity
class Transfer(SQLModel, table=True):
    __tablename__ = "transfers"

    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="accounts.id")
    # in or out
    direction: str
    # The other firm, e.g. Fidelity
    other_broker: str
    account_type: str
    # requested, in_review, in_progress, completed or failed
    status: str
    # "str | None = None" means optional: only failed transfers fill these in
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expected_by: datetime
