from typing import Literal

from pydantic import Field

from assistant.clients.ledger import LedgerClient
from assistant.tools.base import Tool, ToolArgs


# --- Arguments. Notice: none of these has a customer id. The caller's token decides whose data it is. ---


# For tools that need no input
class NoArgs(ToolArgs):
    pass


class WithdrawalsArgs(ToolArgs):
    status: Literal["pending", "completed", "failed", "all"] = Field(
        default="all", description="Which withdrawals to list. Use 'pending' for ones still in progress."
    )


class TransfersArgs(ToolArgs):
    status: Literal["requested", "in_review", "in_progress", "completed", "failed", "all"] = Field(
        default="all", description="Which transfers to list. Use 'failed' to find transfers that had a problem."
    )


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
        "Use to find a transfer or see which ones failed. Do not use for general questions about how transfers work.",
        args_model=TransfersArgs,
        run=get_transfers,
    ),
    Tool(
        name="get_transfer_status",
        description="Get full details of ONE of the customer's own transfers, including the error message if it failed. "
        "Needs the transfer id, which you can get from get_transfers.",
        args_model=TransferStatusArgs,
        run=get_transfer_status,
    ),
]