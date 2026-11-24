from dataclasses import dataclass

from assistant.services.message_parts import split_message_into_parts
from assistant.services.tool_router import declined_reply_for, last_customer_message, route_customer_message
from assistant.tools.base import ToolGroup
from assistant.tools.registry import ToolRegistry


# What will happen to one request in a customer's message: the words of the request, the route it got, and, for a request
# we never help with, the fixed sentence that answers it in place of the model (None means the model answers it)
@dataclass
class PartPlan:
    text: str
    groups: set[ToolGroup] | None
    fixed_sentence: str | None


# Cuts the customer's latest message into its separate requests and routes each one on its own, with the same routing
# function the app uses for a single message. Makes no lookups and no model answer: it only decides what each part gets.
# The customer's latest message must be the last item in "messages" (true in stream_reply: the history ends with the
# message just saved).
async def plan_replies_for_each_part(
        router, messages: list[dict], registry: ToolRegistry, search_help
) -> list[PartPlan]:
    plans = []
    # Everything said before the customer's latest message stays, so a follow-up like "cancel it" keeps its context
    earlier_messages = messages[:-1]
    for part in split_message_into_parts(last_customer_message(messages)):
        # The part takes the place of the full message, it is not added to it
        part_messages = [*earlier_messages, {"role": "user", "content": part}]
        _, groups = await route_customer_message(router, part_messages, registry, search_help)
        plans.append(PartPlan(text=part, groups=groups, fixed_sentence=declined_reply_for(groups)))
    return plans
