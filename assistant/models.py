from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
