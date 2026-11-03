import asyncio
import json

from assistant.tools.base import NoArgs, Tool

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


def run(ledger, name, arguments):
    return json.loads(asyncio.run(registry.execute(ledger, name, arguments)))


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
    async def very_slow(client, args):
        await asyncio.sleep(5)

    slow = Tool(name="slow", description="never finishes in time", args_model=NoArgs, run=very_slow)
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
