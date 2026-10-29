import json
from datetime import datetime
from typing import Literal
from pydantic import BaseModel

from assistant.models import Message


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
