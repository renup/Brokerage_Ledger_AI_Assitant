import asyncio
import json
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlmodel import Session

from assistant.action_types import ActionKind, ActionStatus, AuditAction
from assistant.clients.ledger import LedgerUnavailableError
from assistant.database import engine
from assistant.errors import ActionAlreadyDecidedError, ActionExpiredError, NotFoundError
from assistant.repositories.actions import ActionRepository
from assistant.repositories.audit import AuditRepository
from assistant.services.action_service import ActionService


@pytest.fixture(autouse=True)
def empty_tables():
    with Session(engine) as session:
        session.exec(text("TRUNCATE pending_actions, audit_log"))
        session.commit()


# A fake ledger-core: one transfer whose status a test can change, and a record of retries made
class FakeLedger:
    def __init__(self, status="failed", down=False):
        self.status = status
        self.down = down
        self.retries = []

    async def transfer(self, transfer_id):
        if self.down:
            raise LedgerUnavailableError("down")
        return {"id": transfer_id, "status": self.status}

    async def retry_transfer(self, transfer_id):
        self.retries.append(transfer_id)
        return {"id": transfer_id, "status": "requested"}


@pytest.fixture
def db():
    with Session(engine) as session:
        yield session


def service_for(db, ledger):
    return ActionService(db, ActionRepository(db), AuditRepository(db), ledger)


def propose(service, owner="maya"):
    return service.create_proposal("s1", owner, ActionKind.RETRY_TRANSFER, {"transfer_id": 7}, "Resend transfer #7")


def audit_actions(service, owner="maya"):
    # list_activity is newest first; reverse it to read the story in order
    return [e.action for e in reversed(service.list_activity(owner))]


def test_proposing_changes_nothing_and_is_logged(db):
    ledger = FakeLedger()
    service = service_for(db, ledger)
    proposal = propose(service)
    assert proposal.status == ActionStatus.PROPOSED
    assert ledger.retries == []
    assert audit_actions(service) == [AuditAction.PROPOSED]


def test_approving_runs_the_change_once_and_logs_the_story(db):
    ledger = FakeLedger()
    service = service_for(db, ledger)
    proposal = propose(service)
    done = asyncio.run(service.approve_proposal(proposal.action_id, "maya"))
    assert done.status == ActionStatus.EXECUTED
    assert json.loads(done.result_json) == {"id": 7, "status": "requested"}
    assert ledger.retries == [7]
    assert audit_actions(service) == [AuditAction.PROPOSED, AuditAction.APPROVED, AuditAction.EXECUTED]


def test_approving_twice_runs_the_change_only_once(db):
    ledger = FakeLedger()
    service = service_for(db, ledger)
    proposal = propose(service)
    asyncio.run(service.approve_proposal(proposal.action_id, "maya"))
    with pytest.raises(ActionAlreadyDecidedError):
        asyncio.run(service.approve_proposal(proposal.action_id, "maya"))
    assert ledger.retries == [7]


def test_an_expired_proposal_is_not_run_and_is_marked_expired(db):
    ledger = FakeLedger()
    service = service_for(db, ledger)
    proposal = propose(service)
    # Pretend the 24 hours passed
    proposal.expires_at = proposal.expires_at - timedelta(hours=25)
    db.add(proposal)
    db.commit()
    with pytest.raises(ActionExpiredError):
        asyncio.run(service.approve_proposal(proposal.action_id, "maya"))
    assert ledger.retries == []
    assert audit_actions(service) == [AuditAction.PROPOSED, AuditAction.EXPIRED]


def test_someone_elses_proposal_looks_like_it_does_not_exist(db):
    service = service_for(db, FakeLedger())
    proposal = propose(service, owner="maya")
    with pytest.raises(NotFoundError):
        asyncio.run(service.approve_proposal(proposal.action_id, "renu"))
    with pytest.raises(NotFoundError):
        service.reject_proposal(proposal.action_id, "renu")


def test_a_stale_transfer_is_not_retried(db):
    # The transfer was fixed between the proposal and the approval
    ledger = FakeLedger(status="completed")
    service = service_for(db, ledger)
    proposal = propose(service)
    done = asyncio.run(service.approve_proposal(proposal.action_id, "maya"))
    assert done.status == ActionStatus.FAILED
    assert "completed" in json.loads(done.result_json)["reason"]
    assert ledger.retries == []


def test_ledger_core_being_down_ends_as_failed_not_an_exception(db):
    service = service_for(db, FakeLedger(down=True))
    proposal = propose(service)
    done = asyncio.run(service.approve_proposal(proposal.action_id, "maya"))
    assert done.status == ActionStatus.FAILED
    assert audit_actions(service)[-1] == AuditAction.FAILED


def test_rejecting_then_approving_is_refused(db):
    ledger = FakeLedger()
    service = service_for(db, ledger)
    proposal = propose(service)
    rejected = service.reject_proposal(proposal.action_id, "maya")
    assert rejected.status == ActionStatus.REJECTED
    with pytest.raises(ActionAlreadyDecidedError):
        asyncio.run(service.approve_proposal(proposal.action_id, "maya"))
    assert ledger.retries == []
    assert service.list_open_proposals("maya") == []
