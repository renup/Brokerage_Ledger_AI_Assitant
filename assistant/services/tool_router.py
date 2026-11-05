import logging
import re
from functools import lru_cache
from pathlib import Path

from assistant import llm
from assistant.tools.base import ToolGroup
from assistant.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# How many of the latest messages the router reads, and how much of each. A short look is enough
# to understand "cancel it", and keeps the extra model call fast.
ROUTER_CONTEXT_MESSAGES = 4
ROUTER_MESSAGE_CHARS = 300

# The router's answer when no tool is needed at all
NO_TOOLS_WORD = "none"


# Reads the router's instructions the first time they are needed, then reuses them
@lru_cache
def router_prompt() -> str:
    return (Path(__file__).parent.parent / "prompts" / "router.md").read_text()


# The last few things said, as plain text for the router. Only the customer's and the assistant's
# words: the system rules and the raw lookup results are left out.
def recent_conversation(messages: list[dict]) -> str:
    spoken = [m for m in messages if m["role"] in ("user", "assistant") and m.get("content")]
    return "\n".join(f"{m['role']}: {m['content'][:ROUTER_MESSAGE_CHARS]}" for m in spoken[-ROUTER_CONTEXT_MESSAGES:])


# Turns the router's reply ("account, reference") into a set of groups.
#   a set with groups  -> those groups
#   an empty set       -> the router said "none": no tools needed
#   None               -> the answer made no sense, so the caller should not trust it
def parse_groups(answer: str) -> set[ToolGroup] | None:
    words = set(re.findall(r"[a-z]+", answer.lower()))
    groups = {group for group in ToolGroup if group.value in words}
    if groups:
        return groups
    if NO_TOOLS_WORD in words:
        return set()
    return None


# Decides which tools the model is offered for a message. Offering 3 to 6 tools instead of all of
# them keeps a small model steady as the menu grows.
class ToolRouter:
    # Asks the model one short question. Returns None when it cannot decide.
    async def choose_tool_groups(self, messages: list[dict]) -> set[ToolGroup] | None:
        question = [
            {"role": "system", "content": router_prompt()},
            {"role": "user", "content": recent_conversation(messages)},
        ]
        try:
            # Reuses the one place we talk to the model; this call offers no tools, so it answers in words
            answer = "".join([piece async for piece in llm.stream_turn(question) if isinstance(piece, str)])
        except Exception:
            # Routing is an optimisation. If it breaks, the customer still gets an answer.
            logger.exception("Tool routing failed; offering every tool")
            return None
        groups = parse_groups(answer)
        logger.info("Tool routing: %r -> %s", answer.strip(), groups)
        return groups

    # The registry to use for this message: only the chosen groups' tools. If the router could not
    # decide, every tool is offered, which is exactly how the app behaved before routing.
    async def registry_for_message(self, messages: list[dict], registry: ToolRegistry) -> ToolRegistry:
        groups = await self.choose_tool_groups(messages)
        return registry if groups is None else registry.restricted_to(groups)
