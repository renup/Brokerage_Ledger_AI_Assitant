import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from assistant import llm
from assistant.auth import get_current_user
from assistant.database import engine
from assistant.dependencies import get_ledger_client
from assistant.main import app as assistant_app
from assistant.services.chat_service import ChatService
from assistant.services.tool_router import ToolRouter, parse_groups, recent_conversation, required_calls_for
from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolGroup
from assistant.tools.registry import ToolRegistry
from tests.test_action_service import FakeLedger
from tests.test_assistant import MAYA, parse_sse

registry = ToolRegistry(ALL_TOOLS)


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("account", {ToolGroup.ACCOUNT_DATA}),
        ("account, reference", {ToolGroup.ACCOUNT_DATA, ToolGroup.REFERENCE}),
        ("  Change.\n", {ToolGroup.CHANGES}),
        ("none", set()),
        # A real group wins over "none" if the model says both
        ("none, account", {ToolGroup.ACCOUNT_DATA}),
        ("I think this is about the weather", None),
        ("", None),
    ],
)
def test_the_routers_answer_is_turned_into_groups(answer, expected):
    assert parse_groups(answer) == expected


def test_the_router_sees_only_the_last_few_spoken_messages():
    messages = [
        {"role": "system", "content": "RULES"},
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
        {"role": "assistant", "content": "", "tool_calls": []},
        {"role": "tool", "content": "RAW RESULT"},
        {"role": "user", "content": "three"},
        {"role": "assistant", "content": "four"},
        {"role": "user", "content": "five" + "x" * 500},
    ]
    seen = recent_conversation(messages)
    assert "RULES" not in seen and "RAW RESULT" not in seen
    # Only the last four spoken messages, oldest first, each cut short
    assert seen.splitlines()[0] == "assistant: two"
    assert len(seen.splitlines()) == 4
    assert len(seen.splitlines()[-1]) < 320


def fake_router_model(monkeypatch, answer=None, error=None):
    async def fake_stream(messages, tools=None):
        if error:
            raise error
        yield answer

    monkeypatch.setattr(llm, "stream_turn", fake_stream)


def route(messages=None):
    chosen_registry, _ = asyncio.run(
        ToolRouter().choose_registry_and_groups(messages or [{"role": "user", "content": "hi"}], registry)
    )
    return chosen_registry


def test_a_clear_answer_narrows_the_menu(monkeypatch):
    fake_router_model(monkeypatch, "reference")
    assert set(route().tool_names()) == {"get_fees", "get_tax_documents", "lookup_error_code", "estimate_arrival"}


def test_none_means_no_tools_at_all(monkeypatch):
    fake_router_model(monkeypatch, "none")
    assert route().tool_names() == []


def test_a_nonsense_answer_or_a_broken_router_falls_back_to_every_tool(monkeypatch):
    fake_router_model(monkeypatch, "banana")
    assert route().tool_names() == registry.tool_names()
    fake_router_model(monkeypatch, error=RuntimeError("model down"))
    assert route().tool_names() == registry.tool_names()


@pytest.fixture(autouse=True)
def empty_tables():
    with Session(engine) as session:
        session.exec(text("TRUNCATE messages"))
        session.commit()


# End to end: the chat gives the main model only the routed tools
def test_the_chat_offers_the_main_model_only_the_routed_tools(monkeypatch):
    offered = []

    async def routed_model(messages, tools=None):
        # The routing question offers no tools; the main call is the one that does (or may)
        if "You route a customer's message" in messages[0]["content"]:
            yield "reference"
        else:
            offered.append([t["function"]["name"] for t in tools or []])
            yield "Done."

    async def finds_nothing(question):
        return []

    monkeypatch.setattr(llm, "stream_turn", routed_model)
    monkeypatch.setattr(ChatService, "_help_search_function_for_tools", lambda self, article_names: finds_nothing)
    assistant_app.dependency_overrides[get_current_user] = lambda: MAYA
    assistant_app.dependency_overrides[get_ledger_client] = lambda: FakeLedger()
    try:
        events = parse_sse(TestClient(assistant_app).post("/chat", json={"session_id": "s1", "message": "what are your fees?"}).text)
    finally:
        assistant_app.dependency_overrides.clear()
    assert events[-1][0] == "done"
    assert len(offered) == 1
    # The reference tools, plus the help search: reference questions also depend on what the help articles say
    assert set(offered[0]) == {"get_fees", "get_tax_documents", "lookup_error_code", "estimate_arrival", "search_help_center"}


def test_a_help_route_requires_the_help_search_with_the_customers_last_message():
    messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello"}, {"role": "user", "content": "What is a Roth IRA?"}]
    calls = required_calls_for({ToolGroup.HELP_CENTER}, messages)
    assert [c.name for c in calls] == ["search_help_center"]
    assert json.loads(calls[0].arguments) == {"question": "What is a Roth IRA?"}


@pytest.mark.parametrize("groups", [None, set(), {ToolGroup.ACCOUNT_DATA}, {ToolGroup.REFERENCE, ToolGroup.CHANGES}])
def test_other_routes_require_no_lookups(groups):
    assert required_calls_for(groups, [{"role": "user", "content": "show my accounts"}]) == []


def test_a_very_long_message_is_cut_to_the_length_the_search_tool_accepts():
    calls = required_calls_for({ToolGroup.HELP_CENTER}, [{"role": "user", "content": "x" * 1000}])
    assert len(json.loads(calls[0].arguments)["question"]) == 300


# The router often adds reference and help to an account question. If the help search is forced first, the model already
# holds a tool result and answers from the articles without looking up the customer's own data (measured on the live
# path: 1 of 19 such questions did the lookup). So the search is forced only when the route holds no lookup of the
# customer's own data; on a mixed route the search stays on the menu as an ordinary tool the model may choose.
@pytest.mark.parametrize(
    "groups",
    [
        {ToolGroup.ACCOUNT_DATA, ToolGroup.REFERENCE, ToolGroup.HELP_CENTER},
        {ToolGroup.ACCOUNT_DATA, ToolGroup.HELP_CENTER},
        {ToolGroup.CHANGES, ToolGroup.HELP_CENTER},
        {ToolGroup.CHANGES, ToolGroup.REFERENCE, ToolGroup.HELP_CENTER},
    ],
)
def test_a_route_that_looks_up_the_customers_own_data_does_not_force_the_help_search(groups):
    assert required_calls_for(groups, [{"role": "user", "content": "How much cash do I have?"}]) == []


@pytest.mark.parametrize("groups", [{ToolGroup.HELP_CENTER}, {ToolGroup.REFERENCE, ToolGroup.HELP_CENTER}])
def test_a_route_without_the_customers_own_data_still_forces_the_help_search(groups):
    calls = required_calls_for(groups, [{"role": "user", "content": "Is there a fee for wire withdrawals?"}])
    assert [call.name for call in calls] == ["search_help_center"]


# The customer's own tax forms are in the ledger. A forced article search made the model repeat the article and skip the
# lookup, so on a reference route it is not forced for these.
@pytest.mark.parametrize("question", [
    "Which tax documents do I have on file?",
    "Is my 2026 1099 ready yet?",
    "Where is my 5498?",
    "Are my tax forms available?",
])
def test_a_question_about_the_customers_own_tax_forms_does_not_force_the_help_search(question):
    messages = [{"role": "user", "content": question}]
    assert required_calls_for({ToolGroup.REFERENCE, ToolGroup.HELP_CENTER}, messages) == []


# General tax-form questions, and fee questions that say "my", are still answered from the articles
@pytest.mark.parametrize("question", [
    "When are 5498 forms ready?",
    "What is a 1099-B?",
    "How much fees do I pay on my taxable account?",
    "Is my account charged a fee? And when are tax forms ready?",
])
def test_a_general_tax_or_fee_question_still_forces_the_help_search(question):
    calls = required_calls_for({ToolGroup.REFERENCE, ToolGroup.HELP_CENTER}, [{"role": "user", "content": question}])
    assert [call.name for call in calls] == ["search_help_center"]


# A help-only route has no tax-document lookup on its menu. Skipping the search there would leave the model with nothing
# to answer from, so the search stays forced.
def test_a_help_only_route_forces_the_search_even_for_the_customers_own_tax_forms():
    calls = required_calls_for({ToolGroup.HELP_CENTER}, [{"role": "user", "content": "Why is my 1099 late?"}])
    assert [call.name for call in calls] == ["search_help_center"]
