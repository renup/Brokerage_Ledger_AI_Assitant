from assistant.clients.ledger import LedgerClient
from assistant.tools.base import NoArgs, Tool


# One call to ledger-core, as the caller. The caller's token decides whose accounts these are.
async def get_accounts(client: LedgerClient, args: NoArgs):
    return await client.accounts()


TOOLS = [
    Tool(
        name="get_accounts",
        description="List the customer's own brokerage accounts with type, last 4 digits, cash balance in dollars and status. "
        "Use for questions about balances or which accounts they have.",
        args_model=NoArgs,
        run=get_accounts,
    ),
]
