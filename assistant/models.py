from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from assistant.action_types import ActionStatus
from assistant.config import settings


# One row per chat message, from either the customer or the assistant
class Message(SQLModel, table=True):
    __tablename__ = "messages"

    # A random uuid string, so no counter is needed
    message_id: str = Field(primary_key=True)
    # index=True makes lookups by this column fast (we always search by session)
    session_id: str = Field(index=True)
    # Who owns this conversation. A hash, not the real customer id.
    customer_id_hash: str = Field(index=True)
    # "user" (the customer) or "assistant"
    role: str
    text: str
    # Sources are a list, but SQLite has no list type, so we store it as JSON text
    sources_json: str = "[]"
    # Thumbs "up" or "down"; empty until the customer rates the message
    rating: str | None = None
    # An id for following one request through logs later (Phase 11)
    trace_id: str | None = None
    # The lookups made to produce this reply, as JSON text: one entry per round, each with the
    # call id, tool name, arguments, result and time. Replayed to the model on later turns.
    # server_default fills the column for rows that already exist when the migration runs.
    tool_trace_json: str = Field(default="[]", sa_column_kwargs={"server_default": "[]"})
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# One proposed change waiting for the customer's decision. The model can only create these rows;
# it can never change anything itself.
class PendingAction(SQLModel, table=True):
    __tablename__ = "pending_actions"

    # A random uuid string, like message_id
    action_id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    # Whose proposal this is. A hash, not the real customer id. Every lookup filters on it.
    customer_id_hash: str = Field(index=True)
    # What it would do: an ActionKind value
    kind: str
    # The details as JSON text, e.g. {"transfer_id": 7}. Checked again when approved.
    params_json: str
    # Plain words for the approval sheet, e.g. "Resend IRA transfer from Fidelity"
    summary: str
    # An ActionStatus value
    status: str = ActionStatus.PROPOSED
    # What ledger-core answered, as JSON text, once it has run
    result_json: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # 24 hours after created_at. After this the proposal can no longer be approved.
    expires_at: datetime
    # When the customer approved or rejected it
    decided_at: datetime | None = None


# One line of the Activity screen: who did what, and when. Append only: the code never updates
# or deletes a row (the repository has no method that could).
class AuditEntry(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: int | None = Field(default=None, primary_key=True)
    session_id: str | None = None
    customer_id_hash: str = Field(index=True)
    # An Actor value
    actor: str
    # An AuditAction value
    action: str
    # A plain sentence, e.g. "Proposed: update legal name and resend transfer #7"
    detail: str
    # Which proposal this is about, if any
    action_id: str | None = Field(default=None, index=True)
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# One searchable piece of the help center, stored with the numbers that represent its meaning
class HelpPassage(SQLModel, table=True):
    __tablename__ = "help_passages"
    # A section heading is unique within its article, so (source, heading) identifies a passage
    __table_args__ = (UniqueConstraint("source", "heading"),)

    id: int | None = Field(default=None, primary_key=True)
    # The article's file name, e.g. "fees-and-charges.md"
    source: str = Field(index=True)
    article: str
    heading: str
    text: str
    # A fingerprint of the searchable text. If an article changes, its fingerprint changes and only
    # that passage is embedded again.
    text_hash: str
    # The meaning of the passage as numbers. A normal field type can't be a "vector" column, so we
    # give SQLAlchemy the column directly.
    embedding: list[float] = Field(sa_column=Column(Vector(settings.embedding_dimensions), nullable=False))

