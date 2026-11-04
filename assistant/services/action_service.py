import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import NoReturn

from sqlmodel import Session

from assistant.action_types import ActionKind, ActionStatus, Actor, AuditAction
from assistant.clients.ledger import LedgerClient, LedgerRejectedError, LedgerUnavailableError
from assistant.errors import ActionAlreadyDecidedError, ActionExpiredError, ActionNotPossibleError, NotFoundError
from assistant.models import AuditEntry, PendingAction
from assistant.repositories.actions import ActionRepository
from assistant.repositories.audit import AuditRepository
from assistant.services.action_executors import EXECUTORS

# How long a customer has to decide
PROPOSAL_LIFETIME = timedelta(hours=24)


# All the rules for proposals. It knows nothing about HTTP or SQL. "db" is only here so this
# class can decide where each transaction ends (the repositories never commit): a status change
# and its audit line are saved together, or not at all. "ledger" makes calls as THIS customer.
class ActionService:
    def __init__(self, db: Session, actions: ActionRepository, audit: AuditRepository, ledger: LedgerClient):
        self.db = db
        self.actions = actions
        self.audit = audit
        self.ledger = ledger

    # ---- Public: what routers and the agent's tools call ----

    # Saves a proposal. Nothing is changed in the customer's account yet.
    def create_proposal(self, session_id: str, owner: str, kind: ActionKind, params: dict, summary: str) -> PendingAction:
        # A kind with no executor is a bug in our code, not a customer mistake
        if kind not in EXECUTORS:
            raise ValueError(f"No executor for {kind}")
        proposal = PendingAction(
            action_id=str(uuid.uuid4()),
            session_id=session_id,
            customer_id_hash=owner,
            kind=kind,
            params_json=json.dumps(params),
            summary=summary,
            expires_at=datetime.now(timezone.utc) + PROPOSAL_LIFETIME,
        )
        self.actions.add(proposal)
        self._record_audit_line(proposal, Actor.AGENT, AuditAction.PROPOSED, f"Proposed: {summary}")
        self.db.commit()
        return proposal

    # The proposals still waiting for a decision (the approval sheet)
    def list_open_proposals(self, owner: str) -> list[PendingAction]:
        return self.actions.list_open(owner, datetime.now(timezone.utc))

    # The audit log, newest first (the Activity screen)
    def list_activity(self, owner: str, limit: int = 50) -> list[AuditEntry]:
        return self.audit.list_for_customer(owner, limit)

    # The customer says no. A lapsed proposal can still be rejected; there is nothing to protect.
    def reject_proposal(self, action_id: str, owner: str) -> PendingAction:
        proposal = self._get_proposal_owned_by_customer_or_raise_not_found(action_id, owner)
        now = datetime.now(timezone.utc)
        if not self.actions.transition(action_id, owner, ActionStatus.PROPOSED, ActionStatus.REJECTED, now):
            self.db.rollback()
            raise ActionAlreadyDecidedError(f"This proposal is already {proposal.status}")
        self._record_audit_line(proposal, Actor.CUSTOMER, AuditAction.REJECTED, f"Rejected: {proposal.summary}")
        self.db.commit()
        self.db.refresh(proposal)
        return proposal

    # The customer says yes. The order of steps is the safety:
    #  1. claim it (one atomic statement; only one of two simultaneous approvals can win)
    #  2. save the claim BEFORE calling ledger-core, so a crash leaves a visible "approved" row
    #     instead of a proposal that could be run again
    #  3. re-check the world is still as it was when proposed
    #  4. do it, and record how it ended
    async def approve_proposal(self, action_id: str, owner: str) -> PendingAction:
        proposal = self._get_proposal_owned_by_customer_or_raise_not_found(action_id, owner)
        now = datetime.now(timezone.utc)

        # Friendly early answers. These are NOT the safety (the claim below is); they just give
        # a clear message in the usual cases.
        if proposal.status != ActionStatus.PROPOSED:
            raise ActionAlreadyDecidedError(f"This proposal is already {proposal.status}")
        if proposal.expires_at <= now:
            self._mark_expired_if_still_waiting(proposal, owner, now)
            raise ActionExpiredError("This proposal has expired. Please ask again.")

        claimed = self.actions.transition(
            action_id, owner, ActionStatus.PROPOSED, ActionStatus.APPROVED, now, require_unexpired=True
        )
        if not claimed:
            self.db.rollback()
            self._raise_why_claim_failed(action_id, owner, now)
        self._record_audit_line(proposal, Actor.CUSTOMER, AuditAction.APPROVED, f"Approved: {proposal.summary}")
        self.db.commit()
        return await self._run_approved_change(proposal, owner)

    # ---- Private helpers (the leading underscore means "only this class calls these") ----

    # One of THIS customer's proposals, or NotFoundError (the same error for "no such id" and
    # "someone else's", so nobody can learn that another customer's proposal exists)
    def _get_proposal_owned_by_customer_or_raise_not_found(self, action_id: str, owner: str) -> PendingAction:
        proposal = self.actions.get_for_customer(action_id, owner)
        if proposal is None:
            raise NotFoundError("Proposal not found")
        return proposal

    # Adds one line to the audit log (saved when the caller commits). The proposal supplies the
    # customer, session and proposal id, so callers only say who did what.
    def _record_audit_line(self, proposal: PendingAction, actor: Actor, action: AuditAction, detail: str) -> None:
        self.audit.add(
            AuditEntry(
                customer_id_hash=proposal.customer_id_hash,
                session_id=proposal.session_id,
                actor=actor,
                action=action,
                detail=detail,
                action_id=proposal.action_id,
            )
        )

    # The claim failed. Find out why so the customer gets the right message.
    # (NoReturn: this method always raises.)
    def _raise_why_claim_failed(self, action_id: str, owner: str, now: datetime) -> NoReturn:
        proposal = self._get_proposal_owned_by_customer_or_raise_not_found(action_id, owner)
        self.db.refresh(proposal)
        # Still "proposed" means we lost only because the 24 hours ran out in the last instant
        if proposal.status == ActionStatus.PROPOSED:
            self._mark_expired_if_still_waiting(proposal, owner, now)
            raise ActionExpiredError("This proposal has expired. Please ask again.")
        raise ActionAlreadyDecidedError(f"This proposal is already {proposal.status}")

    # Marks a lapsed proposal "expired", the first time anyone looks at it after it lapsed.
    # No background job needed: the status is only checked when it is used.
    def _mark_expired_if_still_waiting(self, proposal: PendingAction, owner: str, now: datetime) -> None:
        if self.actions.transition(proposal.action_id, owner, ActionStatus.PROPOSED, ActionStatus.EXPIRED, now):
            self._record_audit_line(proposal, Actor.GUARD, AuditAction.EXPIRED, f"Expired: {proposal.summary}")
            self.db.commit()

    # Steps 3 and 4 of approving: re-check, do it, and record how it ended
    async def _run_approved_change(self, proposal: PendingAction, owner: str) -> PendingAction:
        executor = EXECUTORS[ActionKind(proposal.kind)]
        params = json.loads(proposal.params_json)
        try:
            await executor.ensure_still_possible(self.ledger, params)
            result = await executor.perform(self.ledger, params)
        except ActionNotPossibleError as exc:
            return self._record_outcome(proposal, owner, ActionStatus.FAILED, {"reason": str(exc)}, f"Could not run: {exc}")
        except (LedgerRejectedError, LedgerUnavailableError):
            reason = "The account system could not complete it."
            return self._record_outcome(
                proposal, owner, ActionStatus.FAILED, {"reason": reason}, f"Could not run: {proposal.summary}"
            )
        return self._record_outcome(proposal, owner, ActionStatus.EXECUTED, result, f"Done: {proposal.summary}")

    # Saves how an approved proposal ended (its final status, ledger-core's answer, and the audit
    # line) in ONE transaction, then returns the fresh row
    def _record_outcome(
        self, proposal: PendingAction, owner: str, status: ActionStatus, result: dict, detail: str
    ) -> PendingAction:
        self.actions.finish(proposal.action_id, owner, status, json.dumps(result))
        # "executed" and "failed" are also AuditAction values with the same words
        self._record_audit_line(proposal, Actor.AGENT, AuditAction(status.value), detail)
        self.db.commit()
        self.db.refresh(proposal)
        return proposal
