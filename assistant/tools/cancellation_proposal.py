from pydantic import Field

from assistant.action_types import ActionKind
from assistant.tools.base import Tool, ToolArgs, ToolContext


class ProposeWithdrawalCancellationArgs(ToolArgs):
    withdrawal_id: int = Field(description="The id of the PENDING withdrawal to cancel, as returned by get_withdrawals.")


# Prepares a cancellation for the customer to approve. Nothing is cancelled here: the only write is
# a saved proposal row, and the customer's own tap on Approve is what makes it happen.
async def propose_withdrawal_cancellation(context: ToolContext, args: ProposeWithdrawalCancellationArgs):
    # Where proposing is not wired up (for example in evals), say so instead of crashing
    if context.propose is None:
        return {"proposed": False, "reason": "Preparing changes is not available right now."}

    # Look the withdrawal up among the customer's own pending ones. Not finding it covers every
    # case at once: wrong id, someone else's, or already completed, failed or cancelled.
    pending = await context.ledger.withdrawals("pending")
    # next(..., None) gives the first match, or None when there is no match
    withdrawal = next((w for w in pending if w["id"] == args.withdrawal_id), None)
    if withdrawal is None:
        return {
            "proposed": False,
            "reason": f"Withdrawal #{args.withdrawal_id} is not one of the customer's pending withdrawals, so it cannot be cancelled.",
        }

    summary = f"Cancel your ${withdrawal['amount']:,.2f} withdrawal to {withdrawal['bank']}"
    proposal = context.propose(ActionKind.CANCEL_WITHDRAWAL, {"withdrawal_id": args.withdrawal_id}, summary)

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
        name="propose_withdrawal_cancellation",
        description="Prepare a request to cancel ONE of the customer's PENDING withdrawals. This does NOT cancel it: it creates "
        "a request the customer must approve in the app. Use when the customer asks to cancel, stop or undo a withdrawal that "
        "has not arrived yet, or agrees to your offer to. If you do not know the id, call get_withdrawals first. "
        "Never tell the customer it has been cancelled.",
        args_model=ProposeWithdrawalCancellationArgs,
        run=propose_withdrawal_cancellation,
    ),
]
