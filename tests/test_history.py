import json

from assistant.models import Message
from assistant.services.history import REPLAYED_TURNS, replay_reply, trim_to_budget

TRACE = [
    {
        "records": [{"id": "c1", "name": "get_transfers", "arguments": "{}", "result": '{"data": "transfer 7"}'}],
        "at": "2026-11-01T10:00:00+00:00",
    }
]


# A saved row. With_lookups=True gives an assistant reply that used one tool.
def row(role: str, text: str, with_lookups: bool = False) -> Message:
    return Message(
        message_id=text, session_id="s", customer_id_hash="h", role=role, text=text,
        tool_trace_json=json.dumps(TRACE) if with_lookups else "[]",
    )


def test_reply_is_rebuilt_as_request_result_then_words():
    messages = replay_reply(row("assistant", "It failed.", with_lookups=True))
    assert [m["role"] for m in messages] == ["assistant", "tool", "assistant"]
    assert messages[0]["tool_calls"][0]["id"] == "c1"
    assert messages[1]["tool_call_id"] == "c1"
    # The result is labelled as a snapshot with its time
    assert "Looked up at 2026-11-01T10:00:00" in messages[1]["content"]
    assert "transfer 7" in messages[1]["content"]
    assert messages[2]["content"] == "It failed."


def test_reply_without_lookups_is_just_its_words():
    assert replay_reply(row("assistant", "Hi")) == [{"role": "assistant", "content": "Hi"}]


# Newest first, as the repository returns them: 3 assistant replies that each used a tool
def test_only_the_newest_replies_are_replayed():
    newest_first = []
    for n in range(REPLAYED_TURNS + 1):
        newest_first += [row("assistant", f"answer {n}", with_lookups=True), row("user", f"question {n}")]
    messages = trim_to_budget(newest_first, budget=100_000)
    tool_results = [m for m in messages if m["role"] == "tool"]
    assert len(tool_results) == REPLAYED_TURNS


# A tool result must never appear without the request it answers
def test_a_request_is_never_separated_from_its_results():
    newest_first = [row("user", "q2"), row("assistant", "answer", with_lookups=True), row("user", "q1")]
    # Budget big enough for the question only: the whole reply group must be dropped together
    messages = trim_to_budget(newest_first, budget=1)
    assert [m["content"] for m in messages] == ["q2"]
