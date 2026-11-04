import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from assistant import llm
from assistant.auth import get_current_user
from assistant.database import engine
from assistant.dependencies import get_ledger_client
from assistant.llm import ToolCall
from assistant.main import app as assistant_app
from assistant.schemas import ProposalOut
from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolContext
from assistant.tools.registry import ToolRegistry
from tests.test_action_service import FakeLedger
from tests.test_assistant import MAYA, parse_sse

registry = ToolRegistry(ALL_TOOLS)


@pytest.fixture(autouse=True)
def empty_tables():
    with Session(engine) as session:
        session.exec(text("TRUNCATE pending_actions, audit_log, messages"))
        session.commit()


# Stands in for ChatService's saver: records what the tool asked to save, returns a public proposal
class FakeSaver:
    def __init__(self):
        self.saved = []

    def __call__(self, kind, params, summary):
        self.saved.append((kind, params, summary))
        now = datetime.now(timezone.utc)
        return ProposalOut(
            action_id="p1", kind=kind, summary=summary, status="proposed",
            created_at=now, expires_at=now + timedelta(hours=24), decided_at=None, result=None,
        )


def run_tool(ledger, saver, arguments='{"transfer_id": 7}'):
    context = ToolContext(ledger, saver)
    return json.loads(asyncio.run(registry.execute(context, "propose_retry_transfer", arguments)))


def test_proposing_a_failed_transfer_saves_a_proposal_and_changes_nothing():
    ledger, saver = FakeLedger(), FakeSaver()
    result = run_tool(ledger, saver)["data"]
    assert result["proposed"] is True
    assert result["summary"] == "Resend your IRA transfer from Fidelity"
    assert saver.saved == [("retry_transfer", {"transfer_id": 7}, "Resend your IRA transfer from Fidelity")]
    # The tool only proposes: ledger-core's retry endpoint was never called
    assert ledger.retries == []


def test_a_transfer_that_is_not_failed_is_not_proposed():
    saver = FakeSaver()
    result = run_tool(FakeLedger(status="completed"), saver)["data"]
    assert result["proposed"] is False
    assert "completed" in result["reason"]
    assert saver.saved == []


def test_without_a_saver_the_tool_says_it_is_unavailable_instead_of_crashing():
    result = run_tool(FakeLedger(), None)["data"]
    assert result["proposed"] is False


def test_extra_arguments_such_as_a_customer_id_are_refused():
    saver = FakeSaver()
    result = run_tool(FakeLedger(), saver, '{"transfer_id": 7, "customer_id": 2}')
    assert "error" in result
    assert saver.saved == []


# End to end: the model asks for the tool, the chat stream announces the proposal, and the
# proposal shows up in the approval list, with nothing executed.
def test_chat_announces_the_proposal_with_an_approval_required_event(monkeypatch):
    ledger = FakeLedger()
    calls = []

    async def propose_then_answer(messages, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            yield ToolCall(id="c1", name="propose_retry_transfer", arguments='{"transfer_id": 7}')
        else:
            yield "I've prepared it. Please review and approve."

    monkeypatch.setattr(llm, "stream_turn", propose_then_answer)
    assistant_app.dependency_overrides[get_current_user] = lambda: MAYA
    assistant_app.dependency_overrides[get_ledger_client] = lambda: ledger
    try:
        client = TestClient(assistant_app)
        events = parse_sse(client.post("/chat", json={"session_id": "s1", "message": "retry my failed transfer"}).text)
        names = [name for name, _ in events]
        # The sheet event comes after the tool ran and before the closing words
        assert names.index("approval_required") < names.index("token")
        proposal = dict(events)["approval_required"]
        assert proposal["summary"] == "Resend your IRA transfer from Fidelity"
        assert proposal["status"] == "proposed"
        assert [p["action_id"] for p in client.get("/actions").json()] == [proposal["action_id"]]
        assert ledger.retries == []
    finally:
        assistant_app.dependency_overrides.clear()
