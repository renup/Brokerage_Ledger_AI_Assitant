from datetime import datetime, timedelta, timezone

import bcrypt
from sqlmodel import SQLModel, Session

from ledger_core.database import engine
from ledger_core.models import Customer, Account, LinkedBank, Transfer, Withdrawal

# Every demo customer shares this password, so you can log in as anyone
DEMO_PASSWORD = "demo1234"

def hash_password(password: str) -> str:
    # gensalt() adds a random salt, so identical passwords get different hashes.
    # bcrypt works on bytes, so encode() before and decode() after to store it as text.
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def reset_database():
    # Delete every table and all its data, then rebuild them empty
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

def seed():
    reset_database()

    # A session is one conversation with the database; it closes at the end of the block
    with Session(engine) as session:
        # Customers. We don't set id; the database assigns it on commit.
        maya = Customer(
            name="Maya Patel",
            legal_name="Maya R. Patel",
            email="maya.patel@example.com",
            password_hash=hash_password(DEMO_PASSWORD)
        )
        renu = Customer(
            name="Renu Punjabi",
            legal_name="Renu A. Punjabi",
            email="renu.punjabi@example.com",
            password_hash=hash_password(DEMO_PASSWORD)
        )
        raj = Customer(
            name="Raj Manwani",
            legal_name="Raj A. Manwani",
            email="raj.manwani@example.com",
            password_hash=hash_password(DEMO_PASSWORD)
        )
        siya = Customer(
            name="Siya Patel",
            legal_name="Siya B. Patel",
            email="siya.patel@example.com",
            password_hash=hash_password(DEMO_PASSWORD)
        )
        david = Customer(
            name="David Kim",
            legal_name="David R. Kim",
            email="david.kim@example.com",
            password_hash=hash_password(DEMO_PASSWORD)
        )

        # add_all queues the rows; nothing is saved until commit()
        session.add_all([maya, renu, raj, david, siya])
        # Commit now: accounts below need maya.id etc., which exist only after saving
        session.commit()

        # Accounts. Balances are in cents (325075 = $3,250.75).
        # David's is "restricted" to give us mixed statuses.

        maya_individual = Account(customer_id=maya.id, type="individual", number_last4="4821", cash_balance_cents=325075, status="active")
        maya_roth = Account(customer_id=maya.id, type="roth_ira", number_last4="7730", cash_balance_cents=1500000, status="active")
        renu_individual = Account(customer_id=renu.id, type="individual", number_last4="1156", cash_balance_cents=840000, status="active")
        raj_individual = Account(customer_id=raj.id, type="individual", number_last4="9034", cash_balance_cents=500000, status="active")
        david_ira = Account(customer_id=david.id, type="traditional_ira", number_last4="6612", cash_balance_cents=2200000, status="restricted")
        siya_individual = Account(customer_id=siya.id, type="individual", number_last4="2087", cash_balance_cents=125050, status="active")
        session.add_all([maya_individual, maya_roth, renu_individual, raj_individual, david_ira, siya_individual])
        session.commit()

        # Capture the time once. Every date below is relative to it, so the data is always fresh.
        now = datetime.now(timezone.utc)

        # Linked banks (one per customer)

        maya_chase = LinkedBank(customer_id=maya.id, bank_name="Chase", last4="3398")
        renu_bank = LinkedBank(customer_id=renu.id, bank_name="Bank of America", last4="5521")
        raj_bank = LinkedBank(customer_id=raj.id, bank_name="Wells Fargo", last4="7714")
        siya_bank = LinkedBank(customer_id=siya.id, bank_name="Citi", last4="8802")
        david_bank = LinkedBank(customer_id=david.id, bank_name="US Bank", last4="1290")
        session.add_all([maya_chase, renu_bank, raj_bank, siya_bank, david_bank])
        session.commit()

        # Withdrawals. Maya's is the key demo case: $1,200.00 pending to Chase, day 2 of 3.
        # now - timedelta(days=2) means "two days ago".
        maya_withdrawal = Withdrawal(
            account_id=maya_individual.id, bank_id=maya_chase.id,
            amount_cents=120000, status="pending",
            created_at=now - timedelta(days=2), expected_by=now + timedelta(days=1),
            business_day=2, total_days=3,
        )
        renu_withdrawal = Withdrawal(
            account_id=renu_individual.id, bank_id=renu_bank.id,
            amount_cents=50000, status="completed",
            created_at=now - timedelta(days=10), expected_by=now - timedelta(days=7),
            business_day=3, total_days=3,
        )
        raj_withdrawal = Withdrawal(
            account_id=raj_individual.id, bank_id=raj_bank.id,
            amount_cents=250000, status="failed",
            created_at=now - timedelta(days=4), expected_by=now - timedelta(days=1),
            business_day=1, total_days=3,
        )
        siya_withdrawal = Withdrawal(
            account_id=siya_individual.id, bank_id=siya_bank.id,
            amount_cents=20000, status="pending",
            created_at=now - timedelta(days=1), expected_by=now + timedelta(days=2),
            business_day=1, total_days=3,
        )
        session.add_all([maya_withdrawal, renu_withdrawal, raj_withdrawal, siya_withdrawal])

        # Transfers cover the whole lifecycle. Maya's failed IRA transfer (error 214, name
        # mismatch) is the key demo case. The others leave error_code empty (None).
        maya_transfer = Transfer(
            account_id=maya_roth.id, direction="in", other_broker="Fidelity",
            account_type="roth_ira", status="failed",
            error_code="214",
            error_message="Name mismatch: the name on the Fidelity account does not match 'Maya R. Patel'.",
            created_at=now - timedelta(days=5), expected_by=now - timedelta(days=1),
        )
        renu_transfer = Transfer(
            account_id=renu_individual.id, direction="in", other_broker="Schwab",
            account_type="individual", status="completed",
            created_at=now - timedelta(days=30), expected_by=now - timedelta(days=23),
        )
        raj_transfer = Transfer(
            account_id=raj_individual.id, direction="in", other_broker="E*TRADE",
            account_type="individual", status="in_review",
            created_at=now - timedelta(days=2), expected_by=now + timedelta(days=5),
        )
        siya_transfer = Transfer(
            account_id=siya_individual.id, direction="in", other_broker="Robinhood",
            account_type="individual", status="requested",
            created_at=now, expected_by=now + timedelta(days=7),
        )
        david_transfer = Transfer(
            account_id=david_ira.id, direction="in", other_broker="Vanguard",
            account_type="traditional_ira", status="in_progress",
            created_at=now - timedelta(days=3), expected_by=now + timedelta(days=4),
        )
        session.add_all([maya_transfer, renu_transfer, raj_transfer, siya_transfer, david_transfer])
        # Without this final commit, the withdrawals and transfers would be lost
        session.commit()

    print("Seeded customers, accounts, banks, withdrawals and transfers.")

# Runs only when you start this file directly (python -m ledger_core.seed),
# not when another file imports it
if __name__ == "__main__":
    seed()
