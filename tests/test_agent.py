import asyncio
import json

from assistant import llm
from assistant.llm import ToolCall
from assistant.services.agent import MAX_TOOL_ROUNDS, Token, ToolStarted, run_agent


# A stand-in for ToolRegistry: records what it was asked to run
class FakeRegistry:
    def __init__(self):
        self.executed = []

    def definitions(self):
        return [{"type": "function", "function": {"name": "get_accounts"}}]

    async def execute(self, client, name, raw_arguments):
        self.executed.append((name, raw_arguments))
        return json.dumps({"tool": name, "data": ["fake"]})


# Builds a fake model. "turns" is a list; each entry is what the model yields on one call.
# It also records each call's (messages, tools) so tests can inspect what the model was sent.
def fake_model(monkeypatch, turns):
    calls = []

    async def fake_stream_turn(messages, tools=None):
        calls.append((list(messages), tools))
        for item in turns[min(len(calls) - 1, len(turns) - 1)]:
            yield item

    monkeypatch.setattr(llm, "stream_turn", fake_stream_turn)
    return calls


# Runs the agent to the end and returns everything it reported. asyncio.run lets an ordinary
# (non-async) test drive async code, so we need no extra pytest plugin.
def collect(registry):
    async def run():
        return [event async for event in run_agent([{"role": "user", "content": "hi"}], registry, client=None)]

    return asyncio.run(run())


def test_answer_without_tools_streams_words_and_stops(monkeypatch):
    calls = fake_model(monkeypatch, [["Hello", " there"]])
    events = collect(FakeRegistry())
    assert events == [Token("Hello"), Token(" there")]
    assert len(calls) == 1


def test_tool_request_runs_the_tool_then_asks_the_model_again(monkeypatch):
    registry = FakeRegistry()
    request = ToolCall(id="c1", name="get_accounts", arguments="{}")
    calls = fake_model(monkeypatch, [[request], ["You have one account."]])
    events = collect(registry)

    assert events == [ToolStarted("get_accounts"), Token("You have one account.")]
    assert registry.executed == [("get_accounts", "{}")]
    # The second model call saw what it asked for AND the tool's result
    second_call_messages = calls[1][0]
    assert second_call_messages[-2]["tool_calls"][0]["function"]["name"] == "get_accounts"
    assert second_call_messages[-1]["role"] == "tool"
    assert second_call_messages[-1]["tool_call_id"] == "c1"


def test_model_that_never_stops_asking_is_cut_off_and_forced_to_answer(monkeypatch):
    request = ToolCall(id="c", name="get_accounts", arguments="{}")
    # Always asks for a tool, even when no tools are offered
    calls = fake_model(monkeypatch, [[request]])
    collect(FakeRegistry())
    # MAX_TOOL_ROUNDS rounds with tools, then one final call; the final call offers no tools
    assert len(calls) == MAX_TOOL_ROUNDS + 1
    assert calls[-1][1] is None
    assert all(tools is not None for _, tools in calls[:-1])
