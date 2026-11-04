from pydantic import Field

from assistant.action_types import ActionKind
from assistant.tools.base import Tool, ToolArgs, ToolContext, ToolGroup


class ProposeRetryTransferArgs(ToolArgs):
    transfer_id: int = Field(description="The id of the FAILED transfer to resend, as returned by get_transfers.")


# Prepares a retry for the customer to approve. Nothing is changed here: the only write is a
# saved proposal row, and the customer's own tap on Approve is what makes it happen.
async def propose_retry_transfer(context: ToolContext, args: ProposeRetryTransferArgs):
    # Where proposing is not wired up (for example in evals), say so instead of crashing
    if context.propose is None:
        return {"proposed": False, "reason": "Preparing changes is not available right now."}

    # Read the transfer first. This also proves it is the caller's own: someone else's id
    # gives a 404, which the registry already turns into "not found for this customer".
    transfer = await context.ledger.transfer(args.transfer_id)
    if transfer["status"] != "failed":
        return {
            "proposed": False,
            "reason": f"Transfer #{transfer['id']} is {transfer['status']}, so it cannot be retried. Only failed transfers can.",
        }

    # "in" means money coming in from another broker, so the words read "from Fidelity" or "to Fidelity"
    preposition = "from" if transfer["direction"] == "in" else "to"
    summary = f"Resend your {transfer['account_type']} transfer {preposition} {transfer['other_broker']}"
    proposal = context.propose(ActionKind.RETRY_TRANSFER, {"transfer_id": args.transfer_id}, summary)

    return {
        "proposed": True,
        "proposal_id": proposal.action_id,
        "summary": proposal.summary,
        # isoformat() because a datetime cannot be written into the JSON the model reads
        "expires_at": proposal.expires_at.isoformat(),
        "note": "Nothing has been changed yet. The customer must review and approve this in the app.",
    }


TOOLS = [
    Tool(
        name="propose_retry_transfer",
        description="Prepare a request to resend ONE of the customer's failed transfers. This does NOT resend it: it creates "
        "a request the customer must approve in the app. Use when the customer asks to retry, resend, restart or fix a failed "
        "transfer, or agrees to your offer to. If you do not know the id, call get_transfers first. "
        "Never tell the customer it has been resent.",
        args_model=ProposeRetryTransferArgs,
        run=propose_retry_transfer,
        groups=frozenset({ToolGroup.CHANGES}),
    ),
]
