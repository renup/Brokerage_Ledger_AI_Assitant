import asyncio

import pytest
from fastapi.testclient import TestClient

from assistant import llm
from assistant.auth import get_current_user
from assistant.dependencies import get_ledger_client, get_tool_router
from assistant.main import app as assistant_app
from assistant.replies import REPLY_CANNOT_HELP_WITH_THAT, REPLY_ONLY_THEIR_OWN_ACCOUNT
from assistant.services import tool_router
from assistant.services.chat_service import ChatService
from assistant.services.tool_router import (
    declined_reply_for, fixed_reply_for, groups_after_decline_check, groups_after_tax_advice_check, groups_with_help_articles,
    parse_groups, question_asks_for_tax_advice, required_calls_for,
)
from assistant.tools.base import ToolGroup
from tests.test_action_service import FakeLedger
from tests.test_assistant import MAYA, parse_sse


def test_the_router_word_decline_is_understood():
    assert parse_groups("decline") == {ToolGroup.DECLINE_REQUEST}


# A half-sure router must never turn away a real question
def test_decline_next_to_another_word_loses_to_the_other_word():
    assert parse_groups("decline, account") == {ToolGroup.ACCOUNT_DATA}
    assert parse_groups("help, decline") == {ToolGroup.HELP_CENTER}


def test_none_still_means_no_tools_and_is_not_declined():
    assert parse_groups("none") == set()
    assert declined_reply_for(set()) is None


def test_only_a_pure_decline_route_gets_the_fixed_reply():
    assert declined_reply_for({ToolGroup.DECLINE_REQUEST}) == REPLY_CANNOT_HELP_WITH_THAT
    for groups in [{ToolGroup.HELP_CENTER}, {ToolGroup.ACCOUNT_DATA, ToolGroup.REFERENCE}, set(), None]:
        assert declined_reply_for(groups) is None


class DecliningRouter:
    async def choose_registry_and_groups(self, messages, registry):
        groups = {ToolGroup.DECLINE_REQUEST}
        return registry.restricted_to(groups), groups


# The point of declining in code: the model is never asked, so it cannot give the advice
def test_a_declined_request_gets_the_fixed_reply_and_the_model_is_never_asked(monkeypatch):
    times_model_asked = []

    async def finds_nothing(question):
        return []

    monkeypatch.setattr(ChatService, "_help_search_function_for_tools", lambda self, article_names: finds_nothing)

    async def model_that_would_give_advice(messages, tools=None):
        times_model_asked.append(messages)
        yield "Buy VOO."

    monkeypatch.setattr(llm, "stream_turn", model_that_would_give_advice)
    assistant_app.dependency_overrides[get_current_user] = lambda: MAYA
    assistant_app.dependency_overrides[get_ledger_client] = lambda: FakeLedger()
    assistant_app.dependency_overrides[get_tool_router] = lambda: DecliningRouter()
    try:
        client = TestClient(assistant_app)
        events = parse_sse(client.post("/chat", json={"session_id": "decline-1", "message": "Which ETF should I buy?"}).text)
    finally:
        assistant_app.dependency_overrides.clear()

    assert times_model_asked == []
    # The answer guard releases the reply a sentence at a time, so there may be several token events
    assert {name for name, _ in events} == {"token", "done"}
    assert events[-1][0] == "done"
    assert "".join(data["text"] for name, data in events if name == "token") == REPLY_CANNOT_HELP_WITH_THAT


# What the decline check does with the help center's answer. "search" stands in for the real help search.
def run_decline_check(groups, search):
    return asyncio.run(groups_after_decline_check(groups, "Can I cancel it?", search))


def test_a_decline_the_help_center_can_answer_becomes_a_help_question():
    async def finds_a_passage(question):
        return [{"article": "A", "heading": "H", "text": "t", "source": "a.md"}]

    assert run_decline_check({ToolGroup.DECLINE_REQUEST}, finds_a_passage) == {ToolGroup.HELP_CENTER}


def test_a_decline_the_help_center_cannot_answer_stays_declined():
    async def finds_nothing(question):
        return []

    assert run_decline_check({ToolGroup.DECLINE_REQUEST}, finds_nothing) == {ToolGroup.DECLINE_REQUEST}


def test_a_decline_stays_declined_when_the_search_is_slow_or_broken(monkeypatch):
    monkeypatch.setattr(tool_router, "DECLINE_CHECK_SECONDS", 0.05)

    async def too_slow(question):
        await asyncio.sleep(1)
        return [{"article": "A"}]

    async def broken(question):
        raise RuntimeError("embedding service down")

    assert run_decline_check({ToolGroup.DECLINE_REQUEST}, too_slow) == {ToolGroup.DECLINE_REQUEST}
    assert run_decline_check({ToolGroup.DECLINE_REQUEST}, broken) == {ToolGroup.DECLINE_REQUEST}


# The check costs a search only when the router declined: every other route is returned untouched and never searched
def test_other_routes_are_not_searched_or_changed():
    searched = []

    async def search(question):
        searched.append(question)
        return [{"article": "A"}]

    for groups in [{ToolGroup.ACCOUNT_DATA}, {ToolGroup.HELP_CENTER}, set(), None]:
        assert run_decline_check(groups, search) == groups
    assert searched == []


# End to end: the router declined, but the help center has an answer, so the model IS asked, with only the help tool
def test_a_wrongly_declined_question_the_help_center_answers_reaches_the_model(monkeypatch):
    async def finds_a_passage(question):
        return [{"article": "Withdrawals", "heading": "Cancelling", "text": "A completed withdrawal cannot be cancelled.", "source": "w.md"}]

    monkeypatch.setattr(ChatService, "_help_search_function_for_tools", lambda self, article_names: finds_a_passage)
    asked = []

    async def model(messages, tools=None):
        asked.append(messages)
        yield "A completed withdrawal cannot be cancelled."

    monkeypatch.setattr(llm, "stream_turn", model)
    assistant_app.dependency_overrides[get_current_user] = lambda: MAYA
    assistant_app.dependency_overrides[get_ledger_client] = lambda: FakeLedger()
    assistant_app.dependency_overrides[get_tool_router] = lambda: DecliningRouter()
    try:
        client = TestClient(assistant_app)
        events = parse_sse(client.post("/chat", json={"session_id": "decline-2", "message": "Can I cancel a completed withdrawal?"}).text)
    finally:
        assistant_app.dependency_overrides.clear()

    assert len(asked) == 1
    assert "cannot be cancelled" in "".join(data["text"] for name, data in events if name == "token")


class ThirdPartyRouter:
    async def choose_registry_and_groups(self, messages, registry):
        groups = {ToolGroup.THIRD_PARTY_REQUEST}
        return registry.restricted_to(groups), groups


def test_the_router_word_thirdparty_is_understood_and_beats_a_real_group():
    assert parse_groups("thirdparty") == {ToolGroup.THIRD_PARTY_REQUEST}
    # Unlike "decline", it wins over a real group: the router hedged, and acting on someone else's account is the worse mistake
    assert parse_groups("thirdparty, account") == {ToolGroup.THIRD_PARTY_REQUEST}
    assert parse_groups("change, thirdparty") == {ToolGroup.THIRD_PARTY_REQUEST}


def test_a_request_about_someone_else_gets_its_own_reply():
    assert declined_reply_for({ToolGroup.THIRD_PARTY_REQUEST}) == REPLY_ONLY_THEIR_OWN_ACCOUNT
    # Both decline words at once: the stricter one (someone else's account) decides the wording
    assert declined_reply_for({ToolGroup.DECLINE_REQUEST, ToolGroup.THIRD_PARTY_REQUEST}) == REPLY_ONLY_THEIR_OWN_ACCOUNT


def test_the_decline_reply_offers_a_person_so_a_wrong_decline_is_not_a_dead_end():
    assert "person" in REPLY_CANNOT_HELP_WITH_THAT


# The reason for the split: the help center has articles on name changes, but a request about someone else must
# stay declined however much the help center knows about the topic
def test_a_request_about_someone_else_is_never_rescued_by_the_help_center():
    searched = []

    async def finds_a_passage(question):
        searched.append(question)
        return [{"article": "Legal name", "heading": "H", "text": "t", "source": "a.md"}]

    assert run_decline_check({ToolGroup.THIRD_PARTY_REQUEST}, finds_a_passage) == {ToolGroup.THIRD_PARTY_REQUEST}
    assert searched == []


def test_a_request_about_someone_else_gets_the_fixed_reply_and_the_model_is_never_asked(monkeypatch):
    async def finds_a_passage(question):
        return [{"article": "Legal name", "heading": "H", "text": "t", "source": "a.md"}]

    monkeypatch.setattr(ChatService, "_help_search_function_for_tools", lambda self, article_names: finds_a_passage)
    asked = []

    async def model(messages, tools=None):
        asked.append(messages)
        yield "To change your wife's name, use the app."

    monkeypatch.setattr(llm, "stream_turn", model)
    assistant_app.dependency_overrides[get_current_user] = lambda: MAYA
    assistant_app.dependency_overrides[get_ledger_client] = lambda: FakeLedger()
    assistant_app.dependency_overrides[get_tool_router] = lambda: ThirdPartyRouter()
    try:
        client = TestClient(assistant_app)
        events = parse_sse(client.post("/chat", json={"session_id": "third-1", "message": "Fix my wife's legal name"}).text)
    finally:
        assistant_app.dependency_overrides.clear()

    assert asked == []
    assert "".join(data["text"] for name, data in events if name == "token") == REPLY_ONLY_THEIR_OWN_ACCOUNT


# Reference questions (fees, tax forms) also search the help articles, so facts such as "when are 5498 forms ready"
# come from them and not from the model's memory
def test_a_reference_route_also_gets_the_help_center():
    assert groups_with_help_articles({ToolGroup.REFERENCE}) == {ToolGroup.REFERENCE, ToolGroup.HELP_CENTER}
    assert groups_with_help_articles({ToolGroup.ACCOUNT_DATA, ToolGroup.REFERENCE}) == {
        ToolGroup.ACCOUNT_DATA, ToolGroup.REFERENCE, ToolGroup.HELP_CENTER}


def test_other_routes_are_left_alone_by_the_help_articles_step():
    for groups in [{ToolGroup.ACCOUNT_DATA}, {ToolGroup.HELP_CENTER}, {ToolGroup.CHANGES}, {ToolGroup.DECLINE_REQUEST}, set(), None]:
        assert groups_with_help_articles(groups) == groups


# With the help center added, the search runs in code before the model speaks, and the fixed "I don't have that
# information" reply still does NOT fire: the fees tool may answer even when no article does
def test_a_reference_question_searches_the_articles_but_never_gets_the_nothing_found_reply():
    groups = groups_with_help_articles({ToolGroup.REFERENCE})
    assert [call.name for call in required_calls_for(groups, [{"role": "user", "content": "When are 5498 forms ready?"}])] == ["search_help_center"]
    assert fixed_reply_for(groups) is None


# --- tax advice: a question about what the customer owes or can deduct becomes a decline ---

@pytest.mark.parametrize("question", [
    "do I owe tax on my dividends?",
    "How much tax do I need to pay this year on my earnings?",
    "do i hav to pay taxes if i sell",
    "How can I lower my tax bill this year?",
    "Can I deduct my IRA contribution?",
    "what do I pay the government on my earnings in CA?",
    "Am I liable for the gain if I sell my shares next month?",
    "Can I write this loss off against my salary?",
])
def test_a_question_about_what_the_customer_owes_or_can_deduct_is_tax_advice(question):
    assert question_asks_for_tax_advice(question)


@pytest.mark.parametrize("question", [
    "Where is my 1099-B for this year?",
    "Where can I download the year end forms?",
    "When will my tax documents be ready?",
    "What is a 1099-B?",
    "What does tax-advantaged mean for an IRA?",
    "Does the firm report my sales to the IRS?",
    "What is the withdrawal fee?",
    # "Taxable account" is the name of an account type, not a question about tax
    "How much fees do I pay on my taxable account?",
    "Do taxable accounts pay an annual fee?",
    "What do I pay for paper statements on my taxable brokerage account?",
])
def test_tax_forms_and_definitions_are_not_tax_advice(question):
    assert not question_asks_for_tax_advice(question)


def test_a_tax_advice_question_on_a_lookup_route_becomes_a_decline():
    assert groups_after_tax_advice_check({ToolGroup.REFERENCE}, "do I owe tax on my dividends?") == {ToolGroup.DECLINE_REQUEST}
    assert groups_after_tax_advice_check({ToolGroup.HELP_CENTER}, "can I deduct my IRA contribution?") == {ToolGroup.DECLINE_REQUEST}


def test_other_questions_and_routes_keep_the_routers_choice():
    assert groups_after_tax_advice_check({ToolGroup.REFERENCE}, "Where is my 1099-B?") == {ToolGroup.REFERENCE}
    # No answer from the router at all: the app falls back to every tool, which this check does not change
    assert groups_after_tax_advice_check(None, "do I owe tax?") is None
    # The router said "none" (small talk) but the question asks for tax advice: it is declined
    assert groups_after_tax_advice_check(set(), "do I owe tax?") == {ToolGroup.DECLINE_REQUEST}
    assert groups_after_tax_advice_check(set(), "thanks!") == set()


def test_a_change_request_or_third_party_request_is_never_turned_into_a_decline():
    question = "Cancel my withdrawal, and do I owe tax on it?"
    assert groups_after_tax_advice_check({ToolGroup.CHANGES}, question) == {ToolGroup.CHANGES}
    assert groups_after_tax_advice_check({ToolGroup.THIRD_PARTY_REQUEST}, question) == {ToolGroup.THIRD_PARTY_REQUEST}


# Naming the account type must not hide a real tax question asked in the same sentence
@pytest.mark.parametrize("question", [
    "Do I owe tax on the gains in my taxable account?",
    "Is the interest taxable, and how much will I pay?",
    "How can I lower the taxes on my taxable account?",
    # No other tax word, but paying on what an investment earns, or on selling it, is a tax question
    "What will I pay on the gains in my taxable account?",
    "How much will I pay on dividends in my taxable account?",
    "What do I pay if I sell shares in my taxable account?",
])
def test_a_tax_question_that_names_a_taxable_account_is_still_tax_advice(question):
    assert question_asks_for_tax_advice(question)
