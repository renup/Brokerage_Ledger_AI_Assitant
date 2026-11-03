from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from assistant.action_types import ActionKind
from assistant.auth import customer_hash, get_current_user
from assistant.database import engine
from assistant.dependencies import get_ledger_client
from assistant.main import app as assistant_app
from assistant.repositories.actions import ActionRepository
from assistant.repositories.audit import AuditRepository
from assistant.services.action_service import ActionService
from tests.test_action_service import FakeLedger

MAYA = {"id": 1, "name": "Maya Patel", "email": "maya.patel@example.com"}
RENU = {"id": 2, "name": "Renu Punjabi", "email": "renu.punjabi@example.com"}


@pytest.fixture(autouse=True)
def empty_tables():
    with Session(engine) as session:
        session.exec(text("TRUNCATE pending_actions, audit_log"))
        session.commit()


@pytest.fixture
def ledger():
    return FakeLedger()


# A client signed in as the given fake user, with a fake ledger-core behind it
@pytest.fixture
def client_as(ledger):
    def sign_in(user):
        assistant_app.dependency_overrides[get_current_user] = lambda: user
        assistant_app.dependency_overrides[get_ledger_client] = lambda: ledger
        return TestClient(assistant_app)

    yield sign_in
    assistant_app.dependency_overrides.clear()


# Creates a proposal the way the agent's tool will: through the service, not through HTTP
def create_proposal_for(user, expires_in=None) -> str:
    with Session(engine) as db:
        service = ActionService(db, ActionRepository(db), AuditRepository(db), FakeLedger())
        proposal = service.create_proposal(
            "s1", customer_hash(user["id"]), ActionKind.RETRY_TRANSFER, {"transfer_id": 7}, "Resend transfer #7"
        )
        if expires_in is not None:
            proposal.expires_at = proposal.created_at + expires_in
            db.add(proposal)
            db.commit()
        return proposal.action_id


def test_open_proposals_lists_only_my_own(client_as):
    mine = create_proposal_for(MAYA)
    create_proposal_for(RENU)
    body = client_as(MAYA).get("/actions").json()
    assert [p["action_id"] for p in body] == [mine]
    # The public shape never exposes the database's internal columns
    assert "customer_id_hash" not in body[0] and "session_id" not in body[0]


def test_approve_runs_the_change_and_shows_in_activity(client_as, ledger):
    action_id = create_proposal_for(MAYA)
    client = client_as(MAYA)
    response = client.post(f"/actions/{action_id}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "executed"
    assert ledger.retries == [7]
    assert [e["action"] for e in client.get("/activity").json()] == ["executed", "approved", "proposed"]


def test_approving_twice_gives_409_and_runs_once(client_as, ledger):
    action_id = create_proposal_for(MAYA)
    client = client_as(MAYA)
    assert client.post(f"/actions/{action_id}/approve").status_code == 200
    assert client.post(f"/actions/{action_id}/approve").status_code == 409
    assert ledger.retries == [7]


def test_approving_an_expired_proposal_gives_410(client_as, ledger):
    action_id = create_proposal_for(MAYA, expires_in=timedelta(hours=-1))
    assert client_as(MAYA).post(f"/actions/{action_id}/approve").status_code == 410
    assert ledger.retries == []


def test_someone_elses_proposal_gives_404_for_approve_and_reject(client_as, ledger):
    action_id = create_proposal_for(MAYA)
    renu = client_as(RENU)
    assert renu.post(f"/actions/{action_id}/approve").status_code == 404
    assert renu.post(f"/actions/{action_id}/reject").status_code == 404
    assert ledger.retries == []


def test_reject_then_it_leaves_the_open_list(client_as):
    action_id = create_proposal_for(MAYA)
    client = client_as(MAYA)
    assert client.post(f"/actions/{action_id}/reject").json()["status"] == "rejected"
    assert client.get("/actions").json() == []


def test_stale_change_returns_200_with_failed_and_a_reason(client_as, ledger):
    ledger.status = "completed"
    action_id = create_proposal_for(MAYA)
    body = client_as(MAYA).post(f"/actions/{action_id}/approve").json()
    assert body["status"] == "failed"
    assert "completed" in body["result"]["reason"]


def test_endpoints_need_a_token():
    assert TestClient(assistant_app).get("/actions").status_code == 401
