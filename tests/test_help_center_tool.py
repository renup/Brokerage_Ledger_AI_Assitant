import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from assistant import llm
from assistant.auth import get_current_user
from assistant.database import engine
from assistant.dependencies import get_ledger_client, get_tool_router
from assistant.llm import ToolCall
from assistant.main import app as assistant_app
from assistant.repositories.help_passages import HelpPassageRepository
from assistant.services import chat_service
from assistant.services.help_center_service import HelpCenterService
from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolContext, ToolGroup
from assistant.tools.registry import ToolRegistry
from tests.helpers import NoRouting
from tests.test_action_service import FakeLedger
from tests.test_assistant import MAYA, parse_sse
from tests.test_help_center_service import ARTICLES, FakeEmbedder

registry = ToolRegistry(ALL_TOOLS)


@pytest.fixture(autouse=True)
def empty_tables():
    with Session(engine) as session:
        session.exec(text("TRUNCATE help_passages, messages, pending_actions, audit_log"))
        session.commit()


def run_tool(search_help, arguments):
    context = ToolContext(FakeLedger(), search_help=search_help)
    return json.loads(asyncio.run(registry.execute(context, "search_help_center", arguments)))


PASSAGE = {"article": "Fees", "heading": "What we charge", "text": "Trades are free.", "source": "fees.md"}


def test_matching_passages_are_returned_with_the_grounding_note():
    questions = []

    async def search(question):
        questions.append(question)
        return [PASSAGE]

    result = run_tool(search, '{"question": "  what do trades cost  "}')["data"]
    assert questions == ["what do trades cost"]
    assert result["found"] is True and result["passages"] == [PASSAGE]
    assert "Answer only from these passages" in result["note"]


def test_no_close_passage_tells_the_model_to_say_so_and_not_answer_from_memory():
    async def search(question):
        return []

    result = run_tool(search, '{"question": "what is the weather"}')["data"]
    assert result["found"] is False and "Do not answer from memory" in result["note"]


def test_without_a_search_function_the_tool_says_it_is_unavailable_instead_of_crashing():
    assert run_tool(None, '{"question": "anything"}')["data"]["found"] is False


def test_bad_or_extra_arguments_are_refused_before_searching():
    called = []

    async def search(question):
        called.append(question)
        return []

    for bad in ('{}', '{"question": "a"}', '{"question": "' + "x" * 301 + '"}', '{"question": "fees", "customer_id": 2}'):
        assert "error" in run_tool(search, bad)
    assert called == []


def test_the_tool_has_its_own_one_tool_menu():
    assert registry.restricted_to({ToolGroup.HELP_CENTER}).tool_names() == ["search_help_center"]
    assert "search_help_center" not in registry.restricted_to({ToolGroup.REFERENCE}).tool_names()
    assert "search_help_center" not in registry.restricted_to({ToolGroup.ACCOUNT_DATA}).tool_names()


# End to end: the model asks for the tool, the chat service searches the real table (with a fake embedder),
# and the passages reach the model as a tool result.
def test_chat_searches_the_help_center_and_hands_the_passages_to_the_model(monkeypatch):
    embedder = FakeEmbedder()
    with Session(engine) as db:
        asyncio.run(HelpCenterService(db, HelpPassageRepository(db), embedder).index_help_center_articles(ARTICLES))
    monkeypatch.setattr(chat_service, "embed_texts_for_search", embedder)

    calls = []

    async def search_then_answer(messages, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            yield ToolCall(id="c1", name="search_help_center", arguments='{"question": "what do fees cost"}')
        else:
            yield "According to Guide, fees depend on the account."

    monkeypatch.setattr(llm, "stream_turn", search_then_answer)
    assistant_app.dependency_overrides[get_current_user] = lambda: MAYA
    assistant_app.dependency_overrides[get_ledger_client] = lambda: FakeLedger()
    assistant_app.dependency_overrides[get_tool_router] = lambda: NoRouting()
    try:
        events = parse_sse(TestClient(assistant_app).post("/chat", json={"session_id": "s1", "message": "what do fees cost?"}).text)
    finally:
        assistant_app.dependency_overrides.clear()

    assert [name for name, _ in events][-1] == "done"
    tool_messages = [m for m in calls[1] if m["role"] == "tool"]
    assert len(tool_messages) == 1
    # The best match (the Fees passage) came back, not the tax or transfer ones
    assert "what fees cost" in tool_messages[0]["content"]
    assert "tax forms" not in tool_messages[0]["content"]


# Offers only the help-center search and reports the help route, as the real router does for "how does X work?"
class HelpRouting:
    async def choose_registry_and_groups(self, messages, registry):
        groups = {ToolGroup.HELP_CENTER}
        return registry.restricted_to(groups), groups


# The point of searching in code: the model here NEVER asks for the search, yet the passages still reach it,
# and the lookup is saved with the reply for later turns.
def test_on_the_help_route_the_search_runs_even_if_the_model_never_asks(monkeypatch):
    embedder = FakeEmbedder()
    with Session(engine) as db:
        asyncio.run(HelpCenterService(db, HelpPassageRepository(db), embedder).index_help_center_articles(ARTICLES))
    monkeypatch.setattr(chat_service, "embed_texts_for_search", embedder)

    seen = []

    async def only_answers(messages, tools=None):
        seen.append(messages)
        yield "Fees depend on the account."

    monkeypatch.setattr(llm, "stream_turn", only_answers)
    assistant_app.dependency_overrides[get_current_user] = lambda: MAYA
    assistant_app.dependency_overrides[get_ledger_client] = lambda: FakeLedger()
    assistant_app.dependency_overrides[get_tool_router] = lambda: HelpRouting()
    try:
        client = TestClient(assistant_app)
        events = parse_sse(client.post("/chat", json={"session_id": "s2", "message": "what do fees cost?"}).text)
    finally:
        assistant_app.dependency_overrides.clear()

    names = [name for name, _ in events]
    assert "tool" in names and names[-1] == "done"
    # The model was asked once, and already had the search result in front of it
    assert len(seen) == 1
    assert any(m["role"] == "tool" and "what fees cost" in m["content"] for m in seen[0])


# The app is told which article the answer came from, and hears it before "done"
def test_on_the_help_route_the_app_is_told_which_article_the_answer_came_from(monkeypatch):
    embedder = FakeEmbedder()
    with Session(engine) as db:
        asyncio.run(HelpCenterService(db, HelpPassageRepository(db), embedder).index_help_center_articles(ARTICLES))
    monkeypatch.setattr(chat_service, "embed_texts_for_search", embedder)

    async def only_answers(messages, tools=None):
        yield "Fees depend on the account."

    monkeypatch.setattr(llm, "stream_turn", only_answers)
    assistant_app.dependency_overrides[get_current_user] = lambda: MAYA
    assistant_app.dependency_overrides[get_ledger_client] = lambda: FakeLedger()
    assistant_app.dependency_overrides[get_tool_router] = lambda: HelpRouting()
    try:
        client = TestClient(assistant_app)
        events = parse_sse(client.post("/chat", json={"session_id": "s3", "message": "what do fees cost?"}).text)
    finally:
        assistant_app.dependency_overrides.clear()

    names = [name for name, _ in events]
    # Every test passage is in the article "Guide"; the fees question matches only one passage
    assert ("sources", {"articles": ["Guide"]}) in events
    assert names.index("sources") < names.index("done")


# No search, no sources: a reply that did not use the help center must not claim one
def test_a_reply_without_a_help_search_sends_no_sources(monkeypatch):
    async def only_answers(messages, tools=None):
        yield "Hello there."

    monkeypatch.setattr(llm, "stream_turn", only_answers)
    assistant_app.dependency_overrides[get_current_user] = lambda: MAYA
    assistant_app.dependency_overrides[get_ledger_client] = lambda: FakeLedger()
    assistant_app.dependency_overrides[get_tool_router] = lambda: NoRouting()
    try:
        client = TestClient(assistant_app)
        events = parse_sse(client.post("/chat", json={"session_id": "s4", "message": "hi"}).text)
    finally:
        assistant_app.dependency_overrides.clear()

    assert "sources" not in [name for name, _ in events]


# The search ran but found nothing close enough: there is nothing to cite
def test_a_help_search_that_finds_nothing_sends_no_sources(monkeypatch):
    embedder = FakeEmbedder()
    with Session(engine) as db:
        asyncio.run(HelpCenterService(db, HelpPassageRepository(db), embedder).index_help_center_articles(ARTICLES))
    monkeypatch.setattr(chat_service, "embed_texts_for_search", embedder)

    async def only_answers(messages, tools=None):
        yield "I do not have that information."

    monkeypatch.setattr(llm, "stream_turn", only_answers)
    assistant_app.dependency_overrides[get_current_user] = lambda: MAYA
    assistant_app.dependency_overrides[get_ledger_client] = lambda: FakeLedger()
    assistant_app.dependency_overrides[get_tool_router] = lambda: HelpRouting()
    try:
        client = TestClient(assistant_app)
        events = parse_sse(client.post("/chat", json={"session_id": "s5", "message": "what is the weather?"}).text)
    finally:
        assistant_app.dependency_overrides.clear()

    names = [name for name, _ in events]
    assert "tool" in names and "sources" not in names
