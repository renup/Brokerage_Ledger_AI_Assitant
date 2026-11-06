from pydantic import Field

from assistant.tools.base import Tool, ToolArgs, ToolContext, ToolGroup


class HelpSearchArgs(ToolArgs):
    # max_length keeps a rambling model from sending a whole conversation as the search
    question: str = Field(
        min_length=3,
        max_length=300,
        description="What the customer wants to know, in plain words, for example 'how long does a withdrawal take'.",
    )


# Looks up the customer's question in the help-center articles. Read-only.
async def search_help_center(context: ToolContext, args: HelpSearchArgs):
    # Where search is not wired up (for example in evals), say so instead of crashing
    if context.search_help is None:
        return {"found": False, "reason": "Help center search is not available right now."}

    passages = await context.search_help(args.question.strip())
    # Nothing close enough. The model must say so and not fill the gap from memory.
    if not passages:
        return {
            "found": False,
            "note": "The help center has nothing on this. Tell the customer you do not have that information. "
            "Do not answer from memory.",
        }
    return {
        "found": True,
        "passages": passages,
        "note": "Answer only from these passages, in plain words, and name the article each fact came from. "
        "If they do not answer the question, say so.",
    }


TOOLS = [
    Tool(
        name="search_help_center",
        description="Search the help-center articles for how things work here: how long withdrawals and transfers take, "
        "limits, fees policy, what an account type or a tax form is, why a transfer fails. Use for general questions "
        "about the firm's rules. Do not use it for fees, prices or what something costs (use get_fees), for the customer's own "
        "balances, withdrawals or transfers, or for investment advice.",
        args_model=HelpSearchArgs,
        run=search_help_center,
        groups=frozenset({ToolGroup.HELP_CENTER}),
    ),
]