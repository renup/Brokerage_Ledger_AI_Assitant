from assistant.tools import (
    accounts,
    arrival_estimates,
    cancellation_proposal,
    error_codes,
    fees,
    legal_name_proposal,
    retry_proposal,
    tax_documents,
    transfers,
    withdrawal_eligibility,
    withdrawals,
    human_handoff,
)

# The one list of every tool the model may use. To add a tool: write its file, then add it here.
# The order is the order the model sees them in.
ALL_TOOLS = [
    *accounts.TOOLS,
    *withdrawals.TOOLS,
    *withdrawal_eligibility.TOOLS,
    *transfers.TOOLS,
    *error_codes.TOOLS,
    *arrival_estimates.TOOLS,
    *fees.TOOLS,
    *tax_documents.TOOLS,
    *retry_proposal.TOOLS,
    *cancellation_proposal.TOOLS,
    *legal_name_proposal.TOOLS,
    *human_handoff.TOOLS,
]
