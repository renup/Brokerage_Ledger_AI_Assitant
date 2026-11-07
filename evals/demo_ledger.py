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
        return [
            {"account_type": "individual", "number_last4": "1111", "eligible": amount <= 3000,
             "available_to_withdraw": 3000.50, "reasons": [] if amount <= 3000 else ["More than the cash available"]},
            {"account_type": "roth_ira", "number_last4": "2222", "eligible": amount <= 900,
             "available_to_withdraw": 900.00, "reasons": [] if amount <= 900 else ["More than the cash available"]},
        ]

    async def transfers(self, status=None):
        return []

    async def fees(self):
        return []

    async def tax_documents(self, year=None):
        return []
