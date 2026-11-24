import asyncio

from assistant.replies import REPLY_CANNOT_HELP_WITH_THAT
from assistant.services.agent import Token, ToolStarted
from assistant.services.answer_parts import answer_routed_parts_in_order
from assistant.services.routed_parts import RoutedPart
from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolGroup
from assistant.tools.registry import ToolRegistry

registry = ToolRegistry(ALL_TOOLS)

EARLIER = [{"role": "system", "content": "rules"}, {"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello!"}]


# Stands in for run_agent: answers each part with the next prepared answer and remembers what it was given
class AgentThatRemembersWhatItWasGiven:
    def __init__(self, answers):
        self.answers = list(answers)
        self.messages_seen = []
        self.tool_names_seen = []
        self.required_calls_seen = []

    async def __call__(self, messages, part_registry, context, required_calls=None, reply_when_help_finds_nothing=None):
        self.messages_seen.append(messages)
        self.tool_names_seen.append(set(part_registry.tool_names()))
        self.required_calls_seen.append(required_calls)
        yield ToolStarted("a_lookup")
        yield Token(self.answers.pop(0))


def answer(routed_parts, agent):
    # The full message is never shown to the agent: only EARLIER and each part
    messages = [*EARLIER, {"role": "user", "content": " and ".join(p.text for p in routed_parts)}]

    async def collect():
        return [event async for event in answer_routed_parts_in_order(routed_parts, messages, registry, None, agent)]

    return asyncio.run(collect())


def words_of(events):
    return "".join(e.text for e in events if isinstance(e, Token))


def account_part(text):
    return RoutedPart(text=text, groups={ToolGroup.ACCOUNT_DATA}, fixed_sentence=None)


def test_a_declined_part_gets_its_fixed_sentence_and_the_agent_is_never_run_for_it():
    agent = AgentThatRemembersWhatItWasGiven(["Your balance is $5."])
    declined = RoutedPart(text="do I owe tax", groups={ToolGroup.DECLINE_REQUEST}, fixed_sentence=REPLY_CANNOT_HELP_WITH_THAT)

    events = answer([account_part("what is my balance"), declined], agent)

    assert len(agent.messages_seen) == 1
    assert words_of(events) == f"Your balance is $5.\n\n{REPLY_CANNOT_HELP_WITH_THAT}"


def test_the_parts_are_answered_in_the_order_they_were_asked_with_a_blank_line_between():
    agent = AgentThatRemembersWhatItWasGiven(["First answer.", "Second answer."])

    events = answer([account_part("first"), account_part("second")], agent)

    assert words_of(events) == "First answer.\n\nSecond answer."


# Lookup events pass through untouched, so the app can still show "Checking your account…"
def test_lookup_events_from_the_agent_are_passed_on():
    agent = AgentThatRemembersWhatItWasGiven(["Answer."])

    events = answer([account_part("what is my balance")], agent)

    assert ToolStarted("a_lookup") in events


# "redo it for 900" only makes sense if the agent can see the earlier part and its answer
def test_a_later_part_sees_the_earlier_part_and_its_answer_but_never_the_full_message():
    agent = AgentThatRemembersWhatItWasGiven(["Fee is $10.", "Done for 900."])

    answer([account_part("what is the fee"), account_part("redo it for 900")], agent)

    assert agent.messages_seen[0] == [*EARLIER, {"role": "user", "content": "what is the fee"}]
    assert agent.messages_seen[1] == [
        *EARLIER,
        {"role": "user", "content": "what is the fee"},
        {"role": "assistant", "content": "Fee is $10."},
        {"role": "user", "content": "redo it for 900"},
    ]


def test_a_declined_part_and_its_sentence_are_also_remembered_for_the_parts_after_it():
    agent = AgentThatRemembersWhatItWasGiven(["Your balance is $5."])
    declined = RoutedPart(text="do I owe tax", groups={ToolGroup.DECLINE_REQUEST}, fixed_sentence=REPLY_CANNOT_HELP_WITH_THAT)

    answer([declined, account_part("what is my balance")], agent)

    assert agent.messages_seen[0][-3:] == [
        {"role": "user", "content": "do I owe tax"},
        {"role": "assistant", "content": REPLY_CANNOT_HELP_WITH_THAT},
        {"role": "user", "content": "what is my balance"},
    ]


# The point of routing each part: a part is offered only its own tools, and a help part gets its help search run by code
def test_each_part_is_offered_only_its_own_tools_and_a_help_part_gets_the_required_search():
    agent = AgentThatRemembersWhatItWasGiven(["Balance.", "Help answer."])
    help_part = RoutedPart(text="how do transfers work", groups={ToolGroup.HELP_CENTER}, fixed_sentence=None)

    answer([account_part("what is my balance"), help_part], agent)

    assert agent.tool_names_seen[0] == set(registry.restricted_to({ToolGroup.ACCOUNT_DATA}).tool_names())
    assert agent.tool_names_seen[1] == set(registry.restricted_to({ToolGroup.HELP_CENTER}).tool_names())
    assert not agent.required_calls_seen[0]
    assert [call.name for call in agent.required_calls_seen[1]] == ["search_help_center"]
