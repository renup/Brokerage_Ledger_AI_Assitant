from collections.abc import AsyncIterator
from dataclasses import dataclass

from assistant import llm
from assistant.clients.ledger import LedgerClient
from assistant.tools.registry import ToolRegistry

# How many times the model may ask for tools in one customer message. After that we force an answer.
MAX_TOOL_ROUNDS = 3


# What the loop reports to whoever is listening. Plain objects with no HTTP in them:
# ChatService turns these into SSE events.
@dataclass(frozen=True)
class Token:
    text: str


@dataclass(frozen=True)
class ToolStarted:
    name: str


# The model -> tools -> model loop. "messages" is the conversation so far (rules + history).
async def run_agent(
    messages: list[dict], registry: ToolRegistry, client: LedgerClient
) -> AsyncIterator[Token | ToolStarted]:
    # Work on a copy, so tool calls and results don't leak into the caller's list
    conversation = list(messages)

    # One extra pass beyond MAX_TOOL_ROUNDS: the last pass offers no tools, so the model must answer
    for round_number in range(MAX_TOOL_ROUNDS + 1):
        tools = registry.definitions() if round_number < MAX_TOOL_ROUNDS else None

        # Ask the model. Listen to everything it sends back: words go straight to the customer,
        # tool requests are collected until the model has finished this turn.
        tool_calls = []
        async for item in llm.stream_turn(conversation, tools):
            if isinstance(item, str):
                yield Token(item)
            else:
                tool_calls.append(item)

        # No tool requested means the model has answered in words: we are done
        if not tool_calls:
            return

        # Record what the model asked for. The next call needs it to make sense of the results.
        conversation.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                    for c in tool_calls
                ],
            }
        )
        # Run each requested tool (one at a time for now; parallel comes in 5.3) and add its result
        for call in tool_calls:
            yield ToolStarted(call.name)
            result = await registry.execute(client, call.name, call.arguments)
            conversation.append({"role": "tool", "tool_call_id": call.id, "content": result})
