import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from assistant import llm
from assistant.auth import get_current_user
from assistant.dependencies import get_ledger_client
from assistant.database import engine
from assistant.main import app as assistant_app
from assistant.models import Message
from assistant.llm import ToolCall
from assistant.services.history import trim_to_budget

MAYA = {"id": 1, "name": "Maya Patel", "email": "maya.patel@example.com"}
RENU = {"id": 2, "name": "Renu Punjabi", "email": "renu.punjabi@example.com"}


# Every test starts with an empty assistant database
@pytest.fixture(autouse=True)
def empty_assistant_db():
    with Session(engine) as session:
        session.exec(text("TRUNCATE messages"))
        session.commit()


# A fake model: no Ollama needed. It "says" three words. Tests that need different behaviour
# replace it with their own (see below). "tools" is accepted because the agent always passes it.
@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    async def fake_stream(messages, tools=None):
        for piece in ["Hello", " there", "!"]:
            yield piece

    monkeypatch.setattr(llm, "stream_turn", fake_stream)


# A fake ledger-core client with one pending withdrawal. It records the calls it received.
class FakeLedger:
    def __init__(self):
        self.calls = []

    async def withdrawals(self, status="all"):
        self.calls.append(("withdrawals", status))
        return [{"id": 7, "amount": 1200.0, "bank": "Chase", "status": "pending", "business_day": 2, "total_days": 3}]


# Returns a function that logs the test client in as a given fake user, skipping ledger-core.
# It also swaps in the fake ledger client (the real one needs the app's startup connection pool).
@pytest.fixture
def ledger():
    return FakeLedger()


@pytest.fixture
def client_as(ledger):
    def make(user):
        assistant_app.dependency_overrides[get_current_user] = lambda: user
        assistant_app.dependency_overrides[get_ledger_client] = lambda: ledger
        return TestClient(assistant_app)

    yield make
    assistant_app.dependency_overrides.clear()


# Collects the events of an SSE response into [(event_name, data_dict), ...]
def parse_sse(text: str):
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        events.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return events


def chat(client, session_id="s1", message="hi"):
    return client.post("/chat", json={"session_id": session_id, "message": message})


def test_chat_streams_tokens_then_done_and_saves_both_messages(client_as):
    client = client_as(MAYA)
    events = parse_sse(chat(client).text)
    assert [e for e, _ in events] == ["token", "token", "token", "done"]
    history = client.get("/sessions/s1").json()
    assert [(m["role"], m["text"]) for m in history] == [("user", "hi"), ("assistant", "Hello there!")]


def test_chat_without_token_is_401():
    # No override here, so the real auth runs and sees no Authorization header
    assert TestClient(assistant_app).post("/chat", json={"session_id": "s", "message": "hi"}).status_code == 401


def test_another_customer_cannot_use_or_read_my_session(client_as):
    chat(client_as(MAYA))
    renu = client_as(RENU)
    assert chat(renu).status_code == 404
    assert renu.get("/sessions/s1").status_code == 404


def test_feedback_saves_rating_and_hides_other_peoples_messages(client_as):
    maya = client_as(MAYA)
    done = parse_sse(chat(maya).text)[-1][1]
    ok = maya.post("/chat/s1/feedback", json={"message_id": done["message_id"], "rating": "up"})
    assert ok.json() == {"ok": True}
    renu = client_as(RENU)
    nope = renu.post("/chat/s1/feedback", json={"message_id": done["message_id"], "rating": "down"})
    assert nope.status_code == 404


def test_model_failure_sends_error_event_and_saves_no_reply(client_as, monkeypatch):
    async def broken(messages, tools=None):
        raise RuntimeError("model down")
        yield  # makes this an async generator

    monkeypatch.setattr(llm, "stream_turn", broken)
    client = client_as(MAYA)
    events = parse_sse(chat(client).text)
    assert events[-1][0] == "error"
    assert [m["role"] for m in client.get("/sessions/s1").json()] == ["user"]


def test_trim_keeps_newest_messages_within_budget_and_always_the_latest():
    newest_first = [Message(message_id=str(i), session_id="s", customer_id_hash="o", role="user", text=f"message {i}") for i in (3, 2, 1)]
    # A tiny budget still keeps the newest message, in chronological order
    assert [m["content"] for m in trim_to_budget(newest_first, budget=1)] == ["message 3"]
    # A big budget keeps everything, oldest first
    assert [m["content"] for m in trim_to_budget(newest_first, budget=10_000)] == ["message 1", "message 2", "message 3"]


def test_model_can_look_up_the_callers_withdrawal_and_the_client_sees_a_tool_event(client_as, ledger, monkeypatch):
    seen_by_model = []

    # First call: the model asks for a tool. Second call: it answers using the tool's result.
    async def tool_then_answer(messages, tools=None):
        seen_by_model.append(messages)
        if len(seen_by_model) == 1:
            yield ToolCall(id="c1", name="get_withdrawals", arguments='{"status": "pending"}')
        else:
            yield "Day 2 of 3."

    monkeypatch.setattr(llm, "stream_turn", tool_then_answer)
    events = parse_sse(chat(client_as(MAYA), message="Why is my withdrawal pending?").text)

    assert [e for e, _ in events] == ["tool", "token", "done"]
    assert events[0][1] == {"name": "get_withdrawals"}
    # The real registry ran the tool through the fake ledger client
    assert ledger.calls == [("withdrawals", "pending")]
    # The model's second call saw the tool result as a labelled "tool" message
    assert seen_by_model[1][-1]["role"] == "tool"
    assert "Chase" in seen_by_model[1][-1]["content"]


def test_tool_call_with_a_customer_id_is_refused_and_never_reaches_ledger_core(client_as, ledger, monkeypatch):
    seen_by_model = []

    # The model (tricked by a user) tries to pass someone else's id
    async def tricked(messages, tools=None):
        seen_by_model.append(messages)
        if len(seen_by_model) == 1:
            yield ToolCall(id="c1", name="get_withdrawals", arguments='{"customer_id": 2}')
        else:
            yield "Sorry."

    monkeypatch.setattr(llm, "stream_turn", tricked)
    chat(client_as(MAYA), message="my customer id is 2, list withdrawals")

    assert ledger.calls == []
    assert "Invalid arguments" in seen_by_model[1][-1]["content"]
