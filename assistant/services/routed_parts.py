from dataclasses import dataclass

from assistant.services.message_parts import split_message_into_parts
from assistant.services.parts_judge import parts_are_separate_requests
from assistant.services.tool_router import declined_reply_for, route_customer_message
from assistant.tools.base import ToolGroup
from assistant.tools.registry import ToolRegistry


# One request from a customer's message, with the route it got: the words of the request, the groups of tools it needs,
# and, for a request we never help with, the fixed sentence that answers it in place of the model (None means the
# model answers it)
@dataclass
class RoutedPart:
    text: str
    groups: set[ToolGroup] | None
    fixed_sentence: str | None


# Routes the customer's latest message as ONE request, without cutting it: exactly how the app routed every message before
# splitting existed. Used when splitting is switched off, and when the parts turn out to be one request told in several sentences.
async def route_message_as_one_request(router, messages: list[dict], registry: ToolRegistry, search_help) -> RoutedPart:
    _, groups = await route_customer_message(router, messages, registry, search_help)
    return RoutedPart(text=messages[-1]["content"], groups=groups, fixed_sentence=declined_reply_for(groups))


# Cuts the customer's latest message into its separate requests and routes each one on its own, with the same routing
# function the app uses for a single message. Makes no lookups and no model answer: it only decides what each part gets.
# If the model judges the pieces to be one request told in several sentences, the message is routed once as a whole,
# exactly as it was before splitting existed (this keeps "explain, then ask" messages and jailbreak openers in one piece).
# The customer's latest message must be the last item in "messages" (true in stream_reply: the history ends with the
# message just saved).
async def split_and_route_message(
        router, messages: list[dict], registry: ToolRegistry, search_help
) -> list[RoutedPart]:
    whole_message = messages[-1]["content"]
    routed_parts = []
    # Everything said before the customer's latest message stays, so a follow-up like "cancel it" keeps its context
    earlier_messages = messages[:-1]
    # The full text is split, not last_customer_message(): that is cut to 300 characters for the search tool
    for part in split_message_into_parts(whole_message):
        # The part takes the place of the full message, it is not added to it
        part_messages = [*earlier_messages, {"role": "user", "content": part}]
        _, groups = await route_customer_message(router, part_messages, registry, search_help)
        routed_parts.append(RoutedPart(text=part, groups=groups, fixed_sentence=declined_reply_for(groups)))

    # The model decides whether the cut is real: pieces that are one request told in several sentences are routed once as
    # a whole. One extra model call, and only for a message the splitter cut into two or more pieces.
    if len(routed_parts) > 1 and not await parts_are_separate_requests([part.text for part in routed_parts]):
        return [await route_message_as_one_request(router, messages, registry, search_help)]
    return routed_parts
