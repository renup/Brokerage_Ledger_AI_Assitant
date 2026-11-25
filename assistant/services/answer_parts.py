from collections.abc import AsyncIterator, Callable

from assistant.services.agent import Token, ToolRound, ToolStarted, fixed_reply_only, run_agent
from assistant.services.routed_parts import RoutedPart
from assistant.services.tool_router import fixed_reply_for, required_calls_for
from assistant.tools.base import ToolContext
from assistant.tools.registry import ToolRegistry

# What goes between the answers to two parts: a blank line
PART_SEPARATOR = "\n\n"


# Answers a customer's parts one after another and streams the events as run_agent does, so the chat can treat a
# one-part and a many-part message the same way. A part we never help with gets its fixed sentence and no model call;
# any other part gets its own agent run with only its own tools. Each part also sees the parts before it and what was
# answered to them (not the full message), so "redo it for 900" can find what "it" was.
# "messages" ends with the customer's latest message; "agent" is run_agent (a stand-in in the tests).
async def answer_routed_parts_in_order(
        routed_parts: list[RoutedPart],
        messages: list[dict],
        registry: ToolRegistry,
        context: ToolContext,
        agent: Callable = run_agent,
) -> AsyncIterator[Token | ToolStarted | ToolRound]:
    earlier_messages = messages[:-1]
    # The parts answered so far, as the customer's words and the reply each got, ready to show the next part
    answered_so_far = []
    for position, part in enumerate(routed_parts):
        if position > 0:
            yield Token(PART_SEPARATOR)
        part_messages = [*earlier_messages, *answered_so_far, {"role": "user", "content": part.text}]
        if part.fixed_sentence:
            events = fixed_reply_only(part.fixed_sentence)
        else:
            # None means the router could not decide: then every tool is offered, as for a one-part message
            part_registry = registry if part.groups is None else registry.restricted_to(part.groups)
            events = agent(
                part_messages, part_registry, context, required_calls_for(part.groups, part_messages), fixed_reply_for(part.groups)
            )
        words_of_this_part = []
        async for event in events:
            if isinstance(event, Token):
                words_of_this_part.append(event.text)
            yield event
        answered_so_far += [
            {"role": "user", "content": part.text},
            {"role": "assistant", "content": "".join(words_of_this_part)},
        ]
