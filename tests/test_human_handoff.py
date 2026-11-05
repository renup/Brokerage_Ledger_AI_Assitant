import asyncio
import json

from assistant.tools import ALL_TOOLS
from assistant.tools.base import ToolContext
from assistant.tools.registry import ToolRegistry
from tests.test_action_service import FakeLedger

registry = ToolRegistry(ALL_TOOLS)


def run_tool(hand_off, arguments):
    context = ToolContext(FakeLedger(), hand_off=hand_off)
    return json.loads(asyncio.run(registry.execute(context, "escalate_to_human", arguments)))


def test_handoff_passes_a_trimmed_reason_and_returns_the_reference_number():
    reasons = []

    def hand_off(reason):
        reasons.append(reason)
        return 42

    result = run_tool(hand_off, '{"reason": "  wants to dispute a fee  "}')["data"]
    assert reasons == ["wants to dispute a fee"]
    assert result["handed_off"] is True and result["reference"] == 42


def test_handoff_where_it_is_not_wired_up_says_so_instead_of_crashing():
    assert run_tool(None, '{"reason": "complaint"}')["data"]["handed_off"] is False


def test_handoff_rejects_bad_arguments_and_never_records():
    called = []
    for bad in ('{}', '{"reason": ""}', '{"reason": "' + "x" * 301 + '"}', '{"reason": "ok", "customer_id": 2}'):
        assert "error" in run_tool(lambda reason: called.append(reason) or 1, bad)
    assert called == []
