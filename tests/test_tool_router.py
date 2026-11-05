import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from assistant import llm
from assistant.auth import get_current_user
from assistant.database import engine
from assistant.dependencies import get_ledger_client
from assistant.main import app as assistant_app
from assistant.services.tool_router import ToolRouter, parse_groups, recent_conversation
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
    return asyncio.run(ToolRouter().registry_for_message(messages or [{"role": "user", "content": "hi"}], registry))


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

    monkeypatch.setattr(llm, "stream_turn", routed_model)
    assistant_app.dependency_overrides[get_current_user] = lambda: MAYA
    assistant_app.dependency_overrides[get_ledger_client] = lambda: FakeLedger()
    try:
        events = parse_sse(TestClient(assistant_app).post("/chat", json={"session_id": "s1", "message": "what are your fees?"}).text)
    finally:
        assistant_app.dependency_overrides.clear()
    assert events[-1][0] == "done"
    assert len(offered) == 1
    assert set(offered[0]) == {"get_fees", "get_tax_documents", "lookup_error_code", "estimate_arrival"}
