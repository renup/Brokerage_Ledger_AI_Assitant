from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlmodel import Session

from assistant.action_types import ActionKind, ActionStatus, Actor, AuditAction
from assistant.database import engine
from assistant.models import AuditEntry, PendingAction
from assistant.repositories.actions import ActionRepository
from assistant.repositories.audit import AuditRepository

NOW = datetime.now(timezone.utc)


# Every test starts with empty proposal and audit tables
@pytest.fixture(autouse=True)
def empty_tables():
    with Session(engine) as session:
        session.exec(text("TRUNCATE pending_actions, audit_log"))
        session.commit()


# A proposal row with sensible defaults; a test overrides only what it is about
def make_action(action_id="a1", owner="maya", expires_in=timedelta(hours=24), **overrides) -> PendingAction:
    fields = dict(
        action_id=action_id,
        session_id="s1",
        customer_id_hash=owner,
        kind=ActionKind.RETRY_TRANSFER,
        params_json='{"transfer_id": 7}',
        summary="Resend transfer #7",
        expires_at=NOW + expires_in,
    )
    fields.update(overrides)
    return PendingAction(**fields)


# Saves one proposal and commits it, the way the service will
def save(action: PendingAction) -> None:
    with Session(engine) as db:
        ActionRepository(db).add(action)
        db.commit()


# One claim attempt in its own session and transaction. Returns True if it won.
def claim(action_id="a1", owner="maya", require_unexpired=True) -> bool:
    with Session(engine) as db:
        won = ActionRepository(db).transition(
            action_id, owner, ActionStatus.PROPOSED, ActionStatus.APPROVED, NOW, require_unexpired
        )
        db.commit()
        return won


def status_of(action_id="a1", owner="maya") -> str:
    with Session(engine) as db:
        return ActionRepository(db).get_for_customer(action_id, owner).status


def test_second_claim_of_the_same_proposal_loses():
    save(make_action())
    assert claim() is True
    # Already approved, so the "still proposed" condition no longer matches
    assert claim() is False


def test_two_simultaneous_claims_have_exactly_one_winner():
    save(make_action())
    # Two threads, each with its own database connection, claim at the same moment
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sorted(results) == [False, True]
    assert status_of() == ActionStatus.APPROVED


def test_another_customer_cannot_claim_or_see_a_proposal():
    save(make_action(owner="maya"))
    assert claim(owner="renu") is False
    assert status_of(owner="maya") == ActionStatus.PROPOSED
    with Session(engine) as db:
        assert ActionRepository(db).get_for_customer("a1", "renu") is None


def test_an_expired_proposal_cannot_be_approved():
    save(make_action(expires_in=timedelta(hours=-1)))
    assert claim(require_unexpired=True) is False
    assert status_of() == ActionStatus.PROPOSED


def test_reject_does_not_need_to_be_unexpired():
    save(make_action(expires_in=timedelta(hours=-1)))
    with Session(engine) as db:
        rejected = ActionRepository(db).transition("a1", "maya", ActionStatus.PROPOSED, ActionStatus.REJECTED, NOW)
        db.commit()
    assert rejected is True


def test_list_open_hides_expired_decided_and_other_customers():
    save(make_action("open"))
    save(make_action("old", expires_in=timedelta(hours=-1)))
    save(make_action("done", status=ActionStatus.REJECTED))
    save(make_action("theirs", owner="renu"))
    with Session(engine) as db:
        ids = [a.action_id for a in ActionRepository(db).list_open("maya", NOW)]
    assert ids == ["open"]


def test_finish_only_works_on_an_approved_proposal():
    save(make_action())
    with Session(engine) as db:
        repo = ActionRepository(db)
        # Still "proposed", so it cannot jump straight to executed
        repo.finish("a1", "maya", ActionStatus.EXECUTED, '{"ok": true}')
        db.commit()
    assert status_of() == ActionStatus.PROPOSED

    claim()
    with Session(engine) as db:
        ActionRepository(db).finish("a1", "maya", ActionStatus.EXECUTED, '{"ok": true}')
        db.commit()
    assert status_of() == ActionStatus.EXECUTED


def test_audit_log_lists_only_own_entries_newest_first():
    with Session(engine) as db:
        audit = AuditRepository(db)
        audit.add(AuditEntry(customer_id_hash="maya", actor=Actor.AGENT, action=AuditAction.PROPOSED, detail="first", ts=NOW))
        audit.add(AuditEntry(customer_id_hash="maya", actor=Actor.CUSTOMER, action=AuditAction.APPROVED, detail="second", ts=NOW + timedelta(seconds=1)))
        audit.add(AuditEntry(customer_id_hash="renu", actor=Actor.AGENT, action=AuditAction.READ, detail="not yours", ts=NOW))
        db.commit()
        details = [e.detail for e in audit.list_for_customer("maya")]
    assert details == ["second", "first"]


# Append only is a property of the code: the repository must have no way to change history
def test_audit_repository_has_no_update_or_delete():
    methods = {name for name in dir(AuditRepository) if not name.startswith("_")}
    assert methods == {"add", "list_for_customer"}
