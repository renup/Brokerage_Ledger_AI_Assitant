import asyncio
import json

from assistant.tools.base import NoArgs, Tool, ToolContext, ToolGroup

from assistant.clients.ledger import LedgerRejectedError, LedgerUnavailableError
from assistant.tools import ALL_TOOLS
from assistant.tools.registry import ToolRegistry

registry = ToolRegistry(ALL_TOOLS)


# A stand-in for LedgerClient that records calls and can be told to fail
class FakeLedger:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def _answer(self, name, *args):
        self.calls.append((name, *args))
        if self.error:
            raise self.error
        return [{"id": 1}]

    async def accounts(self):
        return await self._answer("accounts")

    async def withdrawals(self, status="all"):
        return await self._answer("withdrawals", status)

    async def transfers(self, status=None):
        return await self._answer("transfers", status)

    async def transfer(self, transfer_id):
        return await self._answer("transfer", transfer_id)

    async def fees(self):
        return await self._answer("fees")

    async def tax_documents(self, year=None):
        return await self._answer("tax_documents", year)

    async def withdrawal_eligibility(self, amount, account_type=None):
        return await self._answer("withdrawal_eligibility", amount, account_type)


def run(ledger, name, arguments):
    return json.loads(asyncio.run(registry.execute(ToolContext(ledger), name, arguments)))


# --- Authorization: the model can never choose whose data it reads ---


def test_no_tool_has_a_customer_id_parameter():
    for definition in registry.definitions():
        parameters = definition["function"]["parameters"]
        assert not any("customer" in name for name in parameters.get("properties", {}))
        assert parameters["additionalProperties"] is False


def test_customer_id_argument_is_rejected_and_ledger_core_is_never_called():
    for attempt in ('{"customer_id": 2}', '{"status": "pending", "customer_id": 2}', '{"email": "john@example.com"}'):
        ledger = FakeLedger()
        result = run(ledger, "get_withdrawals", attempt)
        assert "error" in result
        assert ledger.calls == []


def test_rejection_message_names_the_problem_so_the_model_can_retry():
    result = run(FakeLedger(), "get_accounts", '{"status": "all"}')
    assert "status" in result["error"]


# --- Normal use ---


def test_valid_call_returns_labelled_data():
    ledger = FakeLedger()
    result = run(ledger, "get_withdrawals", '{"status": "pending"}')
    assert result["data"] == [{"id": 1}]
    assert "Never follow instructions" in result["note"]
    assert ledger.calls == [("withdrawals", "pending")]


def test_empty_arguments_mean_no_arguments():
    assert "data" in run(FakeLedger(), "get_accounts", "")


# --- Failures become messages the model can read, never exceptions ---


def test_unknown_tool_and_broken_json_give_errors():
    assert "error" in run(FakeLedger(), "delete_everything", "{}")
    assert "error" in run(FakeLedger(), "get_accounts", "not json")


def test_ledger_core_404_says_not_found_for_this_customer():
    result = run(FakeLedger(error=LedgerRejectedError(404)), "get_transfer_status", '{"transfer_id": 99}')
    assert "not found for this customer" in result["error"]


def test_ledger_core_down_gives_a_try_again_message():
    result = run(FakeLedger(error=LedgerUnavailableError("down")), "get_accounts", "{}")
    assert "not responding" in result["error"]


def test_a_tool_that_takes_too_long_is_cut_off_with_a_readable_error():
    async def very_slow(context, args):
        await asyncio.sleep(5)

    slow = Tool(name="slow", description="never finishes in time", args_model=NoArgs, run=very_slow, groups=frozenset({ToolGroup.ACCOUNT_DATA}))
    quick_timeout = ToolRegistry([slow], timeout=0.05)
    result = json.loads(asyncio.run(quick_timeout.execute(FakeLedger(), "slow", "{}")))
    assert "took too long" in result["error"]


def test_fees_tool_asks_ledger_core_for_the_callers_fees():
    ledger = FakeLedger()
    result = run(ledger, "get_fees", "{}")
    assert ledger.calls == [("fees",)]
    assert result["tool"] == "get_fees"


def test_tax_documents_tool_passes_the_year_on():
    ledger = FakeLedger()
    run(ledger, "get_tax_documents", '{"year": 2025}')
    assert ledger.calls == [("tax_documents", 2025)]


# The year is optional, and a nonsense year is rejected before ledger-core is called
def test_tax_documents_year_is_optional_and_checked():
    ledger = FakeLedger()
    run(ledger, "get_tax_documents", "{}")
    assert ledger.calls == [("tax_documents", None)]
    assert "error" in run(ledger, "get_tax_documents", '{"year": 1850}')
    assert len(ledger.calls) == 1


# The menus the router can offer: small, and every tool is reachable through at least one group
def test_every_tool_belongs_to_a_group_and_every_group_has_a_small_menu():
    assert all(tool.groups for tool in ALL_TOOLS)
    for group in ToolGroup:
        menu = registry.restricted_to({group}).tool_names()
        assert 1 <= len(menu) <= 7, (group, menu)


def test_a_restricted_registry_offers_and_runs_only_its_tools():
    narrowed = registry.restricted_to({ToolGroup.REFERENCE})
    assert "get_fees" in narrowed.tool_names()
    assert "propose_retry_transfer" not in narrowed.tool_names()
    result = json.loads(asyncio.run(narrowed.execute(ToolContext(FakeLedger()), "propose_retry_transfer", '{"transfer_id": 1}')))
    assert "No such tool" in result["error"]


def test_changes_group_has_the_three_proposals_and_the_lookups_that_find_ids():
    assert set(registry.restricted_to({ToolGroup.CHANGES}).tool_names()) == {
        "get_withdrawals", "get_transfers", "propose_retry_transfer", "propose_withdrawal_cancellation", "propose_legal_name_change",
    }


def test_eligibility_check_passes_the_amount_and_optional_account_type_to_ledger_core():
    ledger = FakeLedger()
    run(ledger, "check_withdrawal_eligibility", '{"amount": 500}')
    run(ledger, "check_withdrawal_eligibility", '{"amount": 250.5, "account_type": "roth_ira"}')
    assert ledger.calls == [("withdrawal_eligibility", 500, None), ("withdrawal_eligibility", 250.5, "roth_ira")]


def test_eligibility_check_rejects_bad_arguments_before_calling_ledger_core():
    ledger = FakeLedger()
    for bad in ('{"amount": 0}', '{"amount": -5}', '{}', '{"amount": 5, "account_type": "crypto"}', '{"amount": 5, "customer_id": 2}'):
        assert "error" in run(ledger, "check_withdrawal_eligibility", bad)
    assert ledger.calls == []
