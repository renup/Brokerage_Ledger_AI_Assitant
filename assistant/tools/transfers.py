from typing import Literal

from pydantic import Field

from assistant.clients.ledger import LedgerClient
from assistant.tools.base import Tool, ToolArgs


# Notice: no customer id. The caller's token decides whose transfers these are.
class TransfersArgs(ToolArgs):
    status: Literal["requested", "in_review", "in_progress", "completed", "failed", "all"] = Field(
        default="all",
        description="Which transfers to list. Use 'all' unless the customer names a status. "
        "Use 'failed' to find transfers that had a problem and 'in_progress' for ones still moving.",
    )


class TransferStatusArgs(ToolArgs):
    transfer_id: int = Field(description="The id of one transfer, as returned by get_transfers.")


async def get_transfers(client: LedgerClient, args: TransfersArgs):
    return await client.transfers(args.status)


async def get_transfer_status(client: LedgerClient, args: TransferStatusArgs):
    return await client.transfer(args.transfer_id)


TOOLS = [
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
]
