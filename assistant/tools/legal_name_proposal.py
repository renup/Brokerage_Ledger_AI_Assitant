from pydantic import Field

from assistant.action_types import ActionKind
from assistant.tools.base import Tool, ToolArgs, ToolContext, ToolGroup


class ProposeLegalNameChangeArgs(ToolArgs):
    legal_name: str = Field(
        min_length=1,
        max_length=100,
        description="The new legal name exactly as the customer wrote it, for example 'Maya Rose Patel'. "
        "Never guess, shorten or reformat it.",
    )


# Prepares a legal name change for the customer to approve. Nothing is changed here: the only write
# is a saved proposal row, and the customer's own tap on Approve is what makes it happen.
async def propose_legal_name_change(context: ToolContext, args: ProposeLegalNameChangeArgs):
    # Where proposing is not wired up (for example in evals), say so instead of crashing
    if context.propose is None:
        return {"proposed": False, "reason": "Preparing changes is not available right now."}

    # Spaces around the name are not part of it
    new_name = args.legal_name.strip()
    if not new_name:
        return {"proposed": False, "reason": "The new legal name is empty."}

    # Read the name on file: it goes in the summary, and the approval step compares against it
    # to notice if the name changed in the meantime
    current_name = (await context.ledger.profile())["legal_name"]
    if new_name == current_name:
        return {"proposed": False, "reason": f"The legal name on file is already {current_name}."}

    summary = f"Change your legal name from {current_name} to {new_name}"
    details = {"legal_name": new_name, "previous_legal_name": current_name}
    proposal = context.propose(ActionKind.CHANGE_NAME, details, summary)

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
        name="propose_legal_name_change",
        description="Prepare a request to change the customer's legal name on file. This does NOT change it: it creates "
        "a request the customer must approve in the app. Use only when the customer asks to update or correct their legal "
        "name and has told you the exact new name. If they have not given the new name, ask them for it; never guess it. "
        "Never tell the customer it has been changed.",
        args_model=ProposeLegalNameChangeArgs,
        run=propose_legal_name_change,
        groups=frozenset({ToolGroup.CHANGES}),
    ),
]