from pydantic import Field

from assistant.tools.base import Tool, ToolArgs, ToolContext, ToolGroup


class HandToHumanArgs(ToolArgs):
    # max_length keeps a rambling model from writing an essay into the audit log
    reason: str = Field(
        min_length=3,
        max_length=300,
        description="One short sentence on why a person is needed, for example 'wants to dispute a fee'.",
    )


# Records the hand-off. It does not contact anyone yet; the saved entry is what support would pick up.
async def hand_conversation_to_support(context: ToolContext, args: HandToHumanArgs):
    # Where hand-off is not wired up (for example in evals), say so instead of crashing
    if context.hand_off is None:
        return {"handed_off": False, "reason": "Hand-off to a person is not available right now."}
    reference = context.hand_off(args.reason.strip())
    return {
        "handed_off": True,
        "reference": reference,
        "note": "A support specialist can pick this up. Give the customer the reference number. "
        "Do not promise how fast they will reply.",
    }


TOOLS = [
    Tool(
        name="escalate_to_human",
        description="Hand the customer to a human support specialist. Use when the customer asks to talk to a person, "
        "is upset, or needs something no other tool can do (a dispute, a complaint, closing an account). "
        "Call it right away, without asking the customer why: if they gave no reason, use 'asked to speak to a person'. "
        "Do not use for questions you can answer or for requests another tool handles.",
        args_model=HandToHumanArgs,
        run=hand_conversation_to_support,
        groups=frozenset({ToolGroup.HUMAN_HELP}),
    ),
]
