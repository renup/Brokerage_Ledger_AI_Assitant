from fastapi.testclient import TestClient

from assistant import llm
from assistant.auth import get_current_user
from assistant.dependencies import get_ledger_client, get_tool_router
from assistant.main import app as assistant_app
from assistant.replies import REPLY_CANNOT_HELP_WITH_THAT
from assistant.services.tool_router import declined_reply_for, parse_groups
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
