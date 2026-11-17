import asyncio
import json

from assistant.services.agent import Token, help_search_found_nothing, run_agent
from assistant.services.tool_router import NOTHING_FOUND_REPLY, fixed_reply_for, required_calls_for
from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolContext, ToolGroup
from assistant.tools.registry import ToolRegistry
from assistant import llm

REGISTRY = ToolRegistry(ALL_TOOLS)
QUESTION = [{"role": "user", "content": "Can I trade options in my account?"}]


def search_result(found: bool) -> str:
    return json.dumps({"tool": "search_help_center", "note": "x", "data": {"found": found}})


def test_a_help_only_route_gets_the_fixed_reply():
    assert fixed_reply_for({ToolGroup.HELP_CENTER}) == NOTHING_FOUND_REPLY


def test_any_other_route_keeps_the_model_in_charge():
    for groups in [{ToolGroup.HELP_CENTER, ToolGroup.REFERENCE}, {ToolGroup.ACCOUNT_DATA}, set(), None]:
        assert fixed_reply_for(groups) is None


def test_only_a_search_that_found_nothing_counts_as_found_nothing():
    assert help_search_found_nothing([search_result(False)]) is True
    assert help_search_found_nothing([search_result(True)]) is False
    # A failed search is an error, not an empty result: the model must tell the customer to try again
    assert help_search_found_nothing([json.dumps({"tool": "search_help_center", "error": "took too long"})]) is False
    assert help_search_found_nothing([]) is False


# Runs the agent for one help question; returns what the customer would see and how many times the model was asked
def run_help_question(passages: list[dict], groups, monkeypatch) -> tuple[str, int]:
    asked = []

    async def fake_model(messages, tools=None):
        asked.append(messages)
        yield "The model's own answer."

    async def fake_search(question):
        return passages

    monkeypatch.setattr(llm, "stream_turn", fake_model)
    context = ToolContext(ledger=None, search_help=fake_search)

    async def collect():
        words = []
        async for event in run_agent(QUESTION, REGISTRY, context, required_calls_for(groups, QUESTION),
                                     fixed_reply_for(groups)):
            if isinstance(event, Token):
                words.append(event.text)
        return "".join(words)

    return asyncio.run(collect()), len(asked)


def test_a_help_question_with_nothing_found_gets_the_fixed_reply_and_the_model_is_not_asked(monkeypatch):
    shown, times_model_asked = run_help_question([], {ToolGroup.HELP_CENTER}, monkeypatch)
    assert shown == NOTHING_FOUND_REPLY
    assert times_model_asked == 0


def test_a_help_question_with_a_passage_still_goes_to_the_model(monkeypatch):
    passage = {"article": "A", "heading": "H", "text": "Withdrawals take 3 days.", "source": "a.md"}
    shown, times_model_asked = run_help_question([passage], {ToolGroup.HELP_CENTER}, monkeypatch)
    assert shown == "The model's own answer."
    assert times_model_asked == 1


def test_help_plus_another_route_is_not_cut_short_when_nothing_is_found(monkeypatch):
    shown, times_model_asked = run_help_question([], {ToolGroup.HELP_CENTER, ToolGroup.REFERENCE}, monkeypatch)
    assert shown == "The model's own answer."
    assert times_model_asked == 1
