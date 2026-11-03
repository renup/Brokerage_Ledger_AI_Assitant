from datetime import datetime

from sqlalchemy import update
from sqlmodel import Session, select

from assistant.action_types import ActionStatus
from assistant.models import PendingAction


# Every database query for proposals lives here. Nothing in this class commits: the service
# decides where each transaction ends, so a status change and its audit row succeed or fail together.
class ActionRepository:
    def __init__(self, db: Session):
        self.db = db

    # Queue a new proposal (saved when the service commits)
    def add(self, action: PendingAction) -> None:
        self.db.add(action)

    # One proposal, but only if it belongs to this customer. None means "no such id OR not yours";
    # callers must not be able to tell those apart.
    def get_for_customer(self, action_id: str, owner: str) -> PendingAction | None:
        return self.db.exec(
            select(PendingAction).where(PendingAction.action_id == action_id, PendingAction.customer_id_hash == owner)
        ).first()

    # This customer's proposals that are still waiting and not past their expiry, newest first
    def list_open(self, owner: str, now: datetime) -> list[PendingAction]:
        return list(
            self.db.exec(
                select(PendingAction)
                .where(
                    PendingAction.customer_id_hash == owner,
                    PendingAction.status == ActionStatus.PROPOSED,
                    PendingAction.expires_at > now,
                )
                .order_by(PendingAction.created_at.desc())
            ).all()
        )

    # Move a proposal from one status to another ONLY IF it is still in the status we expect.
    # The check and the change are ONE database statement, so if two requests race (a double tap),
    # the database lets exactly one of them match; the other changes zero rows and gets False.
    # This is how production code decides a race without locks: a compare-and-set.
    def transition(
        self,
        action_id: str,
        owner: str,
        from_status: ActionStatus,
        to_status: ActionStatus,
        now: datetime,
        require_unexpired: bool = False,
    ) -> bool:
        statement = (
            update(PendingAction)
            .where(
                PendingAction.action_id == action_id,
                PendingAction.customer_id_hash == owner,
                PendingAction.status == from_status,
            )
            .values(status=to_status, decided_at=now)
        )
        # Approving also requires that the 24 hours have not passed, decided in the same statement
        if require_unexpired:
            statement = statement.where(PendingAction.expires_at > now)
        # rowcount is how many rows matched: 1 means we won, 0 means someone else got there first
        return self.db.exec(statement).rowcount == 1

    # Record how an approved proposal ended (executed or failed) and what ledger-core answered
    def finish(self, action_id: str, owner: str, status: ActionStatus, result_json: str) -> None:
        self.db.exec(
            update(PendingAction)
            .where(
                PendingAction.action_id == action_id,
                PendingAction.customer_id_hash == owner,
                PendingAction.status == ActionStatus.APPROVED,
            )
            .values(status=status, result_json=result_json)
        )
