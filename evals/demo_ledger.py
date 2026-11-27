# A stand-in for ledger-core with believable data, so the model has something real to answer from.
# Only the lookups needed to trace common questions are filled in; the rest return nothing.
class DemoLedger:
    async def accounts(self):
        return [
            {"id": 1, "type": "individual", "number_last4": "1111", "cash_balance": 4200.50, "status": "active"},
            {"id": 2, "type": "roth_ira", "number_last4": "2222", "cash_balance": 900.00, "status": "active"},
        ]

    async def withdrawals(self, status="all"):
        return [
            {"id": 3, "amount": 1200.0, "bank": "Chase", "status": "pending", "created_at": "2026-11-05T10:00:00Z",
             "expected_by": "2026-11-10T10:00:00Z", "business_day": 2, "total_days": 3}
        ]

    async def withdrawal_eligibility(self, amount, account_type=None):
        # Same fields as ledger-core's answer. available_to_withdraw is the cash minus pending withdrawals.
        rows = [("individual", "1111", 4200.50, 3000.50), ("roth_ira", "2222", 900.00, 900.00)]
        return [
            {
                "account_type": kind,
                "number_last4": last4,
                "eligible": amount <= available,
                "available_to_withdraw": available,
                "cash_balance": cash,
                "cash_balance_after": round(cash - amount, 2) if amount <= available else None,
                "reasons": [] if amount <= available else [f"Only ${available:,.2f} is available after pending withdrawals."],
            }
            for kind, last4, cash, available in rows
            if account_type is None or account_type == kind
        ]

    async def transfers(self, status=None):
        return []

    async def fees(self):
        # (name, dollars, how often, which account type it applies to), for this customer's two accounts
        rows = [
            ("Stock and ETF trades", 0.0, "per_trade", "all"),
            ("Outgoing account transfer", 75.0, "per_transfer_out", "all"),
            ("Outgoing wire withdrawal", 25.0, "per_withdrawal", "all"),
            ("Paper statements", 2.0, "monthly", "all"),
            ("IRA annual fee", 25.0, "annual", "roth_ira"),
        ]
        return [
            {"name": name, "amount": amount, "frequency": frequency, "applies_to": applies_to}
            for name, amount, frequency, applies_to in rows
        ]

    async def tax_documents(self, year=None):
        # (account type, last 4 digits, form, tax year, status, date it is available)
        rows = [
            ("individual", "1111", "1099-B", 2025, "available", "2026-02-15"),
            ("individual", "1111", "1099-DIV", 2025, "available", "2026-02-15"),
            ("roth_ira", "2222", "5498", 2025, "available", "2026-05-31"),
            ("individual", "1111", "1099-B", 2026, "pending", "2027-02-15"),
        ]
        return [
            {"account_type": kind, "number_last4": last4, "form": form, "tax_year": tax_year,
             "status": status, "available_on": available_on}
            for kind, last4, form, tax_year, status, available_on in rows
            if year is None or year == tax_year
        ]
