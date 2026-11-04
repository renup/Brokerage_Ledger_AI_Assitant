import json
from datetime import datetime
from typing import Literal
from pydantic import BaseModel

from assistant.models import Message, AuditEntry, PendingAction


# What the caller sends to POST /chat (moved here from main.py)
class ChatRequest(BaseModel):
    # Which conversation this message belongs to
    session_id: str
    message: str
    # Optional list for images later (Phase 10)
    attachments: list[str] = []


# One message as the caller sees it in GET /sessions/{id}
class MessageOut(BaseModel):
    message_id: str
    role: str
    text: str
    # A list of {"title", "url"} items. Empty for now; real sources arrive in Phase 6.
    sources: list[dict]
    ts: datetime

    # Builds the API shape from a database row, so routers don't repeat this mapping
    @classmethod
    def from_message(cls, m: Message) -> "MessageOut":
        return cls(
            message_id=m.message_id,
            role=m.role,
            text=m.text,
            # Turn the stored JSON text back into a list
            sources=json.loads(m.sources_json),
            ts=m.created_at,
        )


# What the caller sends to the feedback endpoint
class FeedbackRequest(BaseModel):
    # Which reply is being rated (the message_id from the "done" event)
    message_id: str
    # Literal["up", "down"] allows exactly these two words. Anything else gets
    # an automatic 422 error, so the database can only ever hold clean values.
    rating: Literal["up", "down"]


# What the endpoint answers with: {"ok": true}
class FeedbackResponse(BaseModel):
    ok: bool


# One proposal as the app sees it (the approval sheet). Deliberately leaves out the customer
# hash and the session id: the public shape is a choice, not a copy of the database row.
class ProposalOut(BaseModel):
    action_id: str
    # What it would do, e.g. "retry_transfer"
    kind: str
    # Plain words for the sheet, e.g. "Resend transfer #7"
    summary: str
    # proposed, approved, rejected, expired, executed or failed
    status: str
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    # What happened once it ran: ledger-core's answer, or {"reason": ...} if it could not run
    result: dict | None

    @classmethod
    def from_action(cls, a: PendingAction) -> "ProposalOut":
        return cls(
            action_id=a.action_id,
            kind=a.kind,
            summary=a.summary,
            status=a.status,
            created_at=a.created_at,
            expires_at=a.expires_at,
            decided_at=a.decided_at,
            # Turn the stored JSON text back into a dict (None until it has run)
            result=json.loads(a.result_json) if a.result_json else None,
        )


# One line of the Activity screen
class ActivityOut(BaseModel):
    actor: str
    action: str
    detail: str
    # Which proposal it is about, if any
    action_id: str | None
    ts: datetime

    @classmethod
    def from_entry(cls, e: AuditEntry) -> "ActivityOut":
        return cls(actor=e.actor, action=e.action, detail=e.detail, action_id=e.action_id, ts=e.ts)
