from typing import Literal

from pydantic import Field

from assistant.clients.ledger import LedgerClient
from assistant.knowledge.error_codes import explain_error
from assistant.tools.base import Tool, ToolArgs

# --- Arguments. Notice: none of these has a customer id. The caller's token decides whose data it is. ---


# For tools that need no input
class NoArgs(ToolArgs):
    pass


class WithdrawalsArgs(ToolArgs):
    status: Literal["pending", "completed", "failed", "all"] = Field(
        default="all", 
    description="Which withdrawals to list. Use 'all' unless the customer names a status. "
    "Use 'pending' only when they ask about withdrawals still in progress, "
    "'completed' for ones that finished, and 'failed' for ones that had a problem."
    )


class TransfersArgs(ToolArgs):
    status: Literal["requested", "in_review", "in_progress", "completed", "failed", "all"] = Field(
        default="all", 
    description="Which transfers to list. Use 'all' unless the customer names a status. "
    "Use 'failed' to find transfers that had a problem and 'in_progress' for ones still moving."
    )

class ErrorCodeArgs(ToolArgs):
    code: str = Field(description="The error code from a failed transfer, as text, for example '214'.")

class TransferStatusArgs(ToolArgs):
    transfer_id: int = Field(description="The id of one transfer, as returned by get_transfers.")


# --- What each tool does: one call to ledger-core, as the caller ---


async def get_accounts(client: LedgerClient, args: NoArgs):
    return await client.accounts()


async def get_withdrawals(client: LedgerClient, args: WithdrawalsArgs):
    return await client.withdrawals(args.status)


async def get_transfers(client: LedgerClient, args: TransfersArgs):
    return await client.transfers(args.status)


async def get_transfer_status(client: LedgerClient, args: TransferStatusArgs):
    return await client.transfer(args.transfer_id)


# This tool never talks to ledger-core, so it ignores "client". It still takes one so every
# tool has the same shape and the registry can call them all the same way.
async def lookup_error_code(client: LedgerClient, args: ErrorCodeArgs):
    info = explain_error(args.code)
    if info is None:
        # Say plainly that we have nothing, so the model does not invent an explanation
        return {"found": False, "message": "No explanation is on file for this code. Suggest contacting support."}
    return {"found": True, "title": info.title, "meaning": info.meaning, "what_to_do": info.what_to_do}


# --- The list the registry is built from ---

READ_TOOLS = [
    Tool(
        name="get_accounts",
        description="List the customer's own brokerage accounts with type, last 4 digits, cash balance in dollars and status. "
        "Use for questions about balances or which accounts they have.",
        args_model=NoArgs,
        run=get_accounts,
    ),
    Tool(
        name="get_withdrawals",
        description="List the customer's own withdrawals to their bank, with amount, bank, status, and which business day "
        "of the expected total it is on. Use for questions like 'where is my withdrawal' or 'why is it pending'.",
        args_model=WithdrawalsArgs,
        run=get_withdrawals,
    ),
    Tool(
        name="get_transfers",
       description="List the customer's own account transfers to or from other brokers, with status and any error code. "
        "Use for ANY question about the status or progress of one of their transfers, such as "
        "'what's going on with my IRA transfer' or 'did my Fidelity transfer go through'. "
        "Do not use for general questions about how transfers work.",
        args_model=TransfersArgs,
        run=get_transfers,
    ),
    Tool(
        name="get_transfer_status",
        description="Get full details of ONE of the customer's own transfers, including the error message if it failed. "
        "If the customer gives a transfer number, use it directly. Otherwise call get_transfers first to find the id; "
        "never ask the customer for an id.",
        args_model=TransferStatusArgs,
        run=get_transfer_status,
    ),
    Tool(
        name="lookup_error_code",
        description="Explain what a transfer error code means and what the customer can do about it. "
        "Use when the customer asks about a specific error code, or after you find a failed transfer "
        "with an error code. The code is shown in the transfer data; never ask the customer for it.",
        args_model=ErrorCodeArgs,
        run=lookup_error_code,
    ),
]