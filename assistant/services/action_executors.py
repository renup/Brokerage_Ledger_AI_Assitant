from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from assistant.action_types import ActionKind
from assistant.clients.ledger import LedgerClient
from assistant.errors import ActionNotPossibleError


# What it takes to carry out one kind of change. Both functions receive the proposal's details,
# e.g. {"transfer_id": 7}.
#   ensure_still_possible: asks ledger-core whether the change still makes sense RIGHT NOW and
#                          raises ActionNotPossibleError if not
#   perform:               makes the change and returns ledger-core's answer
@dataclass(frozen=True)
class Executor:
    ensure_still_possible: Callable[[LedgerClient, dict], Awaitable[None]]
    perform: Callable[[LedgerClient, dict], Awaitable[dict]]


# A retry only makes sense while the transfer is still failed. The customer may approve hours
# after the proposal, and the transfer may have been fixed or retried by then.
async def ensure_transfer_is_still_failed(ledger: LedgerClient, params: dict) -> None:
    transfer = await ledger.transfer(params["transfer_id"])
    if transfer["status"] != "failed":
        raise ActionNotPossibleError(f"Transfer #{transfer['id']} is now {transfer['status']}, so it cannot be retried.")


async def retry_failed_transfer(ledger: LedgerClient, params: dict) -> dict:
    return await ledger.retry_transfer(params["transfer_id"])

# A cancel only makes sense while the withdrawal is still pending. There is no "get one withdrawal"
# call, so we look for it among the customer's pending ones: if it is not there, it has moved on
# (completed, failed, already cancelled) or was never theirs.
async def ensure_withdrawal_is_still_pending(ledger: LedgerClient, params: dict) -> None:
    pending = await ledger.withdrawals("pending")
    if params["withdrawal_id"] not in [w["id"] for w in pending]:
        raise ActionNotPossibleError(f"Withdrawal #{params['withdrawal_id']} is no longer pending, so it cannot be cancelled.")


async def perform_withdrawal_cancellation(ledger: LedgerClient, params: dict) -> dict:
    return await ledger.cancel_withdrawal(params["withdrawal_id"])


# kind -> how to do it. Name change and cancel withdrawal get an entry here when their
# ledger-core endpoints exist; the service itself will not change.
EXECUTORS: dict[ActionKind, Executor] = {
    ActionKind.RETRY_TRANSFER: Executor(
        ensure_still_possible=ensure_transfer_is_still_failed, perform=retry_failed_transfer
    ),
    ActionKind.CANCEL_WITHDRAWAL: Executor(
        ensure_still_possible=ensure_withdrawal_is_still_pending, perform=perform_withdrawal_cancellation
    ),
}

