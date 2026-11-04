import asyncio
import json

from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolContext
from assistant.tools.registry import ToolRegistry
from tests.test_action_service import FakeLedger
from tests.test_retry_proposal import FakeSaver

registry = ToolRegistry(ALL_TOOLS)


def run_tool(ledger, saver, arguments='{"legal_name": "Maya Rose Patel"}'):
    context = ToolContext(ledger, saver)
    return json.loads(asyncio.run(registry.execute(context, "propose_legal_name_change", arguments)))


def test_proposing_changes_nothing_and_stores_old_and_new_names():
    ledger, saver = FakeLedger(), FakeSaver()
    result = run_tool(ledger, saver)["data"]
    assert result["proposed"] is True
    assert result["summary"] == "Change your legal name from Maya R. Patel to Maya Rose Patel"
    kind, details, _ = saver.saved[0]
    assert kind == "change_name"
    assert details == {"legal_name": "Maya Rose Patel", "previous_legal_name": "Maya R. Patel"}
    assert ledger.name_updates == []


def test_spaces_around_the_new_name_are_trimmed():
    saver = FakeSaver()
    run_tool(FakeLedger(), saver, '{"legal_name": "  Maya Rose Patel  "}')
    assert saver.saved[0][1]["legal_name"] == "Maya Rose Patel"


def test_the_same_name_is_not_proposed():
    saver = FakeSaver()
    result = run_tool(FakeLedger(), saver, '{"legal_name": "Maya R. Patel"}')["data"]
    assert result["proposed"] is False and saver.saved == []


def test_an_empty_or_too_long_name_is_refused_before_anything_is_saved():
    saver = FakeSaver()
    assert "error" in run_tool(FakeLedger(), saver, '{"legal_name": ""}')
    assert "error" in run_tool(FakeLedger(), saver, json.dumps({"legal_name": "x" * 101}))
    assert saver.saved == []


def test_a_customer_id_argument_is_refused():
    saver = FakeSaver()
    assert "error" in run_tool(FakeLedger(), saver, '{"legal_name": "Maya Rose Patel", "customer_id": 2}')
    assert saver.saved == []


def test_without_a_saver_the_tool_says_it_is_unavailable_instead_of_crashing():
    assert run_tool(FakeLedger(), None)["data"]["proposed"] is False
