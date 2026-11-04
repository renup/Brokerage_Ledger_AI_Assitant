from typing import Literal

from pydantic import Field

from assistant.tools.base import Tool, ToolArgs, ToolContext


# Notice: no customer id. The caller's token decides whose withdrawals these are.
class WithdrawalsArgs(ToolArgs):
    status: Literal["pending", "completed", "failed", "cancelled", "all"] = Field(
        default="all",
        description="Which withdrawals to list. Use 'all' unless the customer names a status. "
        "Use 'pending' only when they ask about withdrawals still in progress, "
        "'completed' for ones that finished, and 'failed' for ones that had a problem.",
    )


async def get_withdrawals(context: ToolContext, args: WithdrawalsArgs):
    return await context.ledger.withdrawals(args.status)


TOOLS = [
    Tool(
        name="get_withdrawals",
        description="List the customer's own withdrawals to their bank, with amount, bank, status, and which business day "
        "of the expected total it is on. Use for questions like 'where is my withdrawal' or 'why is it pending'.",
        args_model=WithdrawalsArgs,
        run=get_withdrawals,
    ),
]
