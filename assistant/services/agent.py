import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from assistant import llm
from assistant.clients.ledger import LedgerClient
from assistant.tools.registry import ToolRegistry

# How many times the model may ask for tools in one customer message. After that we force an answer.
MAX_TOOL_ROUNDS = 3
# The most tool calls we will actually run for one customer message, however the model asks
MAX_TOOL_CALLS = 6


# What the loop reports to whoever is listening. Plain objects with no HTTP in them:
# ChatService turns these into SSE events.
@dataclass(frozen=True)
class Token:
    text: str


@dataclass(frozen=True)
class ToolStarted:
    name: str


# The model -> tools -> model loop. "messages" is the conversation so far (rules + history).
#
# Think of it as a conversation with a very capable assistant who cannot open your files:
#   1. You hand over the question and a menu of lookups they may ask you to do.
#   2. They either answer, or say "please look up X (and Y)".
#   3. You do the lookups yourself and hand back the results.
#   4. They read the results and answer (or ask for more lookups, up to a limit).
# Each trip through the "for" loop below is one such round.
async def run_agent(
    messages: list[dict], registry: ToolRegistry, client: LedgerClient
) -> AsyncIterator[Token | ToolStarted]:
    # Work on a copy, so tool calls and results don't leak into the caller's list
    conversation = list(messages)
    # How many tool calls we have run so far for this one customer message
    calls_run = 0

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

        # Safety limit: only run as many calls as still fit under MAX_TOOL_CALLS in total.
        # "room" is how many are left; the list is cut into the ones we run and the ones we skip.
        room = MAX_TOOL_CALLS - calls_run
        to_run, skipped = tool_calls[:room], tool_calls[room:]
        calls_run += len(to_run)

        # Tell the listener which lookups are starting (the app can show "Checking your account…")
        for call in to_run:
            yield ToolStarted(call.name)

        # Do all the lookups AT THE SAME TIME instead of one after another. If two lookups take
        # 1 second each, this finishes in about 1 second, not 2. gather() waits until every one is
        # done and gives the results back in the same order as to_run, so each result still
        # lines up with the request it answers.
        results = await asyncio.gather(*(registry.execute(client, c.name, c.arguments) for c in to_run))

        # Hand each result back to the model, labelled with the id of the request it answers
        for call, result in zip(to_run, results):
            conversation.append({"role": "tool", "tool_call_id": call.id, "content": result})

        # The model must get an answer to EVERY request it made, or its next turn is malformed.
        # For requests we refused to run (over the limit), the answer is "too many lookups".
        for call in skipped:
            limit_result = registry.error_result(call.name, "Too many lookups for one question. Answer with what you have.")
            conversation.append({"role": "tool", "tool_call_id": call.id, "content": limit_result})
