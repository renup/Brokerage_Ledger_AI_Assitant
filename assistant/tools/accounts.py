from assistant.tools.base import NoArgs, Tool, ToolContext


# One call to ledger-core, as the caller. The caller's token decides whose accounts these are.
async def get_accounts(context: ToolContext, args: NoArgs):
    return await context.ledger.accounts()


TOOLS = [
    Tool(
        name="get_accounts",
        description="List the customer's own brokerage accounts with type, last 4 digits, cash balance in dollars and status. "
        "Use for questions about balances or which accounts they have.",
        args_model=NoArgs,
        run=get_accounts,
    ),
]
