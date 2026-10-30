import asyncio
import json
import time

from assistant import llm
from assistant.llm import ToolCall
from assistant.services.agent import MAX_TOOL_CALLS, MAX_TOOL_ROUNDS, Token, ToolStarted, run_agent


# A stand-in for ToolRegistry: records what it was asked to run.
# "delay" makes every tool take that many seconds, to prove calls overlap.
class FakeRegistry:
    def __init__(self, delay=0.0):
        self.executed = []
        self.delay = delay

    @staticmethod
    def error_result(name, message):
        return json.dumps({"tool": name, "error": message})

    def definitions(self):
        return [{"type": "function", "function": {"name": "get_accounts"}}]

    async def execute(self, client, name, raw_arguments):
        await asyncio.sleep(self.delay)
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


def test_tools_requested_together_run_at_the_same_time_and_results_keep_their_order(monkeypatch):
    registry = FakeRegistry(delay=0.2)
    requests = [ToolCall(id=f"c{i}", name="get_accounts", arguments="{}") for i in range(3)]
    calls = fake_model(monkeypatch, [requests, ["Done."]])

    started = time.monotonic()
    collect(registry)
    elapsed = time.monotonic() - started

    # Three 0.2s tools one after another would take 0.6s; side by side they take about 0.2s
    assert elapsed < 0.45
    # Each result is still attached to the request it answers, in the original order
    tool_messages = [m for m in calls[1][0] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["c0", "c1", "c2"]


def test_more_than_the_limit_runs_only_the_limit_but_every_request_gets_an_answer(monkeypatch):
    registry = FakeRegistry()
    requests = [ToolCall(id=f"c{i}", name="get_accounts", arguments="{}") for i in range(MAX_TOOL_CALLS + 2)]
    calls = fake_model(monkeypatch, [requests, ["Done."]])
    collect(registry)

    assert len(registry.executed) == MAX_TOOL_CALLS
    tool_messages = [m for m in calls[1][0] if m["role"] == "tool"]
    # All 8 requests were answered; the last 2 were told "too many lookups"
    assert len(tool_messages) == MAX_TOOL_CALLS + 2
    assert all("Too many lookups" in m["content"] for m in tool_messages[MAX_TOOL_CALLS:])
