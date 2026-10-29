import logging
import uuid
from collections.abc import AsyncIterator, Callable
from functools import lru_cache
from pathlib import Path

from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from assistant.config import settings
from assistant.database import new_session
from assistant.errors import NotFoundError
from assistant.llm import stream_chat
from assistant.models import Message
from assistant.repositories.messages import MessageRepository
from assistant.services.history import trim_to_budget
from assistant.sse import sse

logger = logging.getLogger(__name__)


# Reads the system prompt file the first time it is needed, then reuses it
@lru_cache
def system_prompt() -> str:
    return (Path(__file__).parent.parent / "prompts" / "system.md").read_text()


# All the chat logic. It knows nothing about HTTP: routers call it, it calls the repository
# and the model. "repo" is this request's repository; "session_factory" opens a fresh
# database session for work that outlives the request (saving after a stream ends).
class ChatService:
    def __init__(self, repo: MessageRepository, session_factory: Callable[[], Session] = new_session):
        self.repo = repo
        self.session_factory = session_factory

    # Step 1 of a chat turn, run during the request: check the session is allowed, save the
    # customer's message, and build what the model will see (rules + trimmed history).
    def prepare_turn(self, session_id: str, owner: str, first_name: str, text: str) -> list[dict]:
        # Is this session id already used by a DIFFERENT customer? Refuse as "not found",
        # so we don't reveal that someone else's session exists.
        if self.repo.session_owned_by_someone_else(session_id, owner):
            raise NotFoundError("Session not found")

        # Save the customer's message before replying
        self.repo.add(
            Message(message_id=str(uuid.uuid4()), session_id=session_id, customer_id_hash=owner, role="user", text=text)
        )

        # History already includes the message we just saved, so the model sees the new question too
        history = trim_to_budget(
            self.repo.list_for_session(session_id, owner, newest_first=True),
            settings.history_token_budget,
        )
        # The system message always comes first and carries the rules, with the customer's name swapped in
        rules = {"role": "system", "content": system_prompt().replace("{first_name}", first_name)}
        return [rules] + history

    # Step 2, run while the response streams: forward the model's words as SSE events,
    # then save the full reply. Yields ready-to-send SSE text.
    async def stream_reply(self, messages: list[dict], session_id: str, owner: str) -> AsyncIterator[str]:
        message_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())

        parts = []
        try:
            async for piece in stream_chat(messages):
                parts.append(piece)
                yield sse("token", {"text": piece})
        except Exception:
            # Log the real cause for us; tell the client only something safe
            logger.exception("Model call failed (trace_id=%s)", trace_id)
            yield sse("error", {"message": "The assistant is unavailable right now. Please try again"})
            return

        reply = Message(
            message_id=message_id,
            session_id=session_id,
            customer_id_hash=owner,
            role="assistant",
            text="".join(parts),
            trace_id=trace_id,
        )
        # Save in a worker thread so the (blocking) database call doesn't freeze other streams
        await run_in_threadpool(self._save_reply, reply)

        # Save first, then say "done", so a client never hears "done" about an unsaved reply
        yield sse("done", {"message_id": message_id, "trace_id": trace_id})

    # Uses its OWN session: the request's session may already be closed when a stream ends
    def _save_reply(self, reply: Message) -> None:
        with self.session_factory() as db:
            MessageRepository(db).add(reply)

    # A session's messages, oldest first. Empty means "no such session, or not yours".
    def get_history(self, session_id: str, owner: str) -> list[Message]:
        messages = self.repo.list_for_session(session_id, owner)
        if not messages:
            raise NotFoundError("Session not found")
        return messages

    # Save a thumbs up/down. The repository only finds the message if all four conditions hold,
    # so any failure gives the same "not found" and reveals nothing about other people's messages.
    def rate_reply(self, session_id: str, message_id: str, owner: str, rating: str) -> None:
        message = self.repo.get_assistant_message(message_id, session_id, owner)
        if message is None:
            raise NotFoundError("Message not found")
        self.repo.set_rating(message, rating)
