from pydantic import Field

from assistant.clients.ledger import LedgerClient
from assistant.knowledge.error_codes import explain_error
from assistant.tools.base import Tool, ToolArgs


class ErrorCodeArgs(ToolArgs):
    code: str = Field(description="The error code from a failed transfer, as text, for example '214'.")


# This tool never talks to ledger-core, so it ignores "client". It still takes one so every
# tool has the same shape and the registry can call them all the same way.
async def lookup_error_code(client: LedgerClient, args: ErrorCodeArgs):
    info = explain_error(args.code)
    if info is None:
        # Say plainly that we have nothing, so the model does not invent an explanation
        return {"found": False, "message": "No explanation is on file for this code. Suggest contacting support."}
    return {"found": True, "title": info.title, "meaning": info.meaning, "what_to_do": info.what_to_do}


TOOLS = [
    Tool(
        name="lookup_error_code",
        description="Explain what a transfer error code means and what the customer can do about it. "
        "Use when the customer asks about a specific error code, or after you find a failed transfer "
        "with an error code. The code is shown in the transfer data; never ask the customer for it.",
        args_model=ErrorCodeArgs,
        run=lookup_error_code,
    ),
]
