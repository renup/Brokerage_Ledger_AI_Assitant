import asyncio
import json

from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolContext
from assistant.tools.registry import ToolRegistry
from tests.test_action_service import FakeLedger
from tests.test_retry_proposal import FakeSaver

registry = ToolRegistry(ALL_TOOLS)


def run_tool(ledger, saver, arguments='{"withdrawal_id": 3}'):
    context = ToolContext(ledger, saver)
    return json.loads(asyncio.run(registry.execute(context, "propose_withdrawal_cancellation", arguments)))


def test_proposing_cancels_nothing_and_saves_a_proposal():
    ledger, saver = FakeLedger(), FakeSaver()
    result = run_tool(ledger, saver)["data"]
    assert result["proposed"] is True
    assert result["summary"] == "Cancel your $1,200.00 withdrawal to Chase"
    assert saver.saved == [("cancel_withdrawal", {"withdrawal_id": 3}, "Cancel your $1,200.00 withdrawal to Chase")]
    assert ledger.cancellations == []


def test_a_withdrawal_that_is_not_pending_or_not_theirs_is_not_proposed():
    saver = FakeSaver()
    # Id 99 is not among the customer's pending withdrawals (completed, someone else's, or made up)
    result = run_tool(FakeLedger(), saver, '{"withdrawal_id": 99}')["data"]
    assert result["proposed"] is False
    assert saver.saved == []


def test_without_a_saver_the_tool_says_it_is_unavailable_instead_of_crashing():
    assert run_tool(FakeLedger(), None)["data"]["proposed"] is False


def test_extra_arguments_such_as_a_customer_id_are_refused():
    saver = FakeSaver()
    result = run_tool(FakeLedger(), saver, '{"withdrawal_id": 3, "customer_id": 2}')
    assert "error" in result and saver.saved == []
