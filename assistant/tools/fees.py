from assistant.clients.ledger import LedgerClient
from assistant.tools.base import NoArgs, Tool


async def get_fees(client: LedgerClient, args: NoArgs):
    return await client.fees()


TOOLS = [
    Tool(
        name="get_fees",
        description="List the fees that apply to the customer's own accounts, with the amount in dollars, "
        "how often it is charged, and a short description. Use for questions about what something costs, "
        "such as charges for moving an account out, wires, statements or account upkeep. "
        "Do not use for how much money is in an account.",
        args_model=NoArgs,
        run=get_fees,
    ),
]
