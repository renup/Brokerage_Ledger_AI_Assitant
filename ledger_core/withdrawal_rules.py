from ledger_core.models import Account

# The most one withdrawal may be, in cents ($25,000)
MAX_SINGLE_WITHDRAWAL_CENTS = 2_500_000


# Dollars with thousands separators, for the reasons shown to the customer
def dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


# Cash that can still be withdrawn: the balance minus what pending withdrawals already claim.
# Never negative.
def available_to_withdraw_cents(account: Account, pending_withdrawal_cents: int) -> int:
    return max(account.cash_balance_cents - pending_withdrawal_cents, 0)


# What the account's cash would be after this withdrawal goes through, in cents. Plain subtraction; the caller
# decides whether to show it (it is only meaningful when the withdrawal is allowed).
def cash_balance_after_withdrawal_cents(account: Account, amount_cents: int) -> int:
    return account.cash_balance_cents - amount_cents


# The reasons a withdrawal of this size from this account is not allowed. An empty list means it IS allowed.
# A pure function (no database), so each rule can be tested on its own.
def find_reasons_withdrawal_is_blocked(account: Account, pending_withdrawal_cents: int, amount_cents: int) -> list[str]:
    reasons = []
    if account.status != "active":
        reasons.append(f"The account is {account.status}.")
    available = available_to_withdraw_cents(account, pending_withdrawal_cents)
    if amount_cents > available:
        reasons.append(f"Only {dollars(available)} is available after pending withdrawals.")
    if amount_cents > MAX_SINGLE_WITHDRAWAL_CENTS:
        reasons.append(f"Withdrawals over {dollars(MAX_SINGLE_WITHDRAWAL_CENTS)} need to be split or handled by support.")
    return reasons
