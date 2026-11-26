import asyncio

from assistant.services.agent import Token, ToolRecord, ToolRound
from assistant.services.answer_guard import ANSWER_STOPPED_MESSAGE, AnswerGuard
from assistant.services.answer_parts import PartStarted, answer_routed_parts_in_order
from assistant.services.routed_parts import RoutedPart
from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolGroup
from assistant.tools.registry import ToolRegistry
from tests import test_multi_part_chat

registry = ToolRegistry(ALL_TOOLS)


# A ledger lookup in one part must not switch off the turnaround check for the next part: the help part has no ledger
# data behind its "business days", so an unbacked one has to be stopped
def test_turnaround_times_are_checked_again_when_the_next_part_starts():
    guard = AnswerGuard()
    guard.stop_checking_turnarounds_for_this_answer()
    assert guard.release_completed_sentences("It arrives in 99 business days. ") == ["It arrives in 99 business days. "]

    guard.start_next_part()

    assert guard.release_completed_sentences("Transfers take 98 business days. ") == [ANSWER_STOPPED_MESSAGE]
    assert guard.stopped_because


# Every part announces itself, so the chat can tell where one part ends and the next begins
def test_each_part_starts_with_a_part_started_event():
    async def agent(messages, part_registry, context, required_calls=None, reply_when_help_finds_nothing=None):
        yield Token("An answer.")

    parts = [RoutedPart(text=text, groups={ToolGroup.ACCOUNT_DATA}, fixed_sentence=None) for text in ("first", "second")]
    messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "first and second"}]

    async def collect():
        return [event async for event in answer_routed_parts_in_order(parts, messages, registry, None, agent)]

    events = asyncio.run(collect())

    assert [type(event) for event in events] == [PartStarted, Token, Token, PartStarted, Token]


# The whole chat: the lookup happens in part 1, the unbacked turnaround is said in part 2, and the customer never sees it
def test_a_ledger_lookup_in_one_part_does_not_excuse_an_unbacked_turnaround_in_the_next(monkeypatch):
    lookup = ToolRecord(id="1", name="get_withdrawals", arguments="{}", result='{"data": {"status": "pending"}}')

    async def two_parts(routed_parts, messages, registry, context, agent=None):
        yield PartStarted()
        yield ToolRound(records=(lookup,), at="now")
        yield Token("Your withdrawal is pending.")
        yield Token("\n\n")
        yield PartStarted()
        yield Token("Transfers take 98 business days.")

    monkeypatch.setattr("assistant.services.chat_service.answer_routed_parts_in_order", two_parts)

    events, _ = test_multi_part_chat.chat(monkeypatch, "where is my withdrawal and how long do transfers take", splitting_on=True)

    words = "".join(data["text"] for name, data in events if name == "token")
    assert "Your withdrawal is pending." in words
    assert "98 business days" not in words
