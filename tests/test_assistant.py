import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel

from assistant.auth import get_current_user
from assistant.database import engine
from assistant.main import app as assistant_app
from assistant.models import Message
from assistant.services import chat_service
from assistant.services.history import trim_to_budget

MAYA = {"id": 1, "name": "Maya Patel", "email": "maya.patel@example.com"}
RENU = {"id": 2, "name": "Renu Punjabi", "email": "renu.punjabi@example.com"}


# Every test starts with an empty assistant database
@pytest.fixture(autouse=True)
def empty_assistant_db():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


# A fake model: no Ollama needed. It "says" three words.
@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    async def fake_stream(messages):
        for piece in ["Hello", " there", "!"]:
            yield piece

    monkeypatch.setattr(chat_service, "stream_chat", fake_stream)


# Returns a function that logs the test client in as a given fake user, skipping ledger-core
@pytest.fixture
def client_as():
    def make(user):
        assistant_app.dependency_overrides[get_current_user] = lambda: user
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
    async def broken(messages):
        raise RuntimeError("model down")
        yield  # makes this an async generator

    monkeypatch.setattr(chat_service, "stream_chat", broken)
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
