import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from assistant.config import settings
from assistant.database import new_session
from assistant.errors import NotFoundError
from assistant.models import Message
from assistant.repositories.messages import MessageRepository
from assistant.repositories.actions import ActionRepository
from assistant.repositories.audit import AuditRepository
from assistant.schemas import ProposalOut
from assistant.services.action_service import ActionService
from assistant.services.history import trim_to_budget
from assistant.sse import sse
from assistant.services.tool_router import ToolRouter
from assistant.clients.embeddings import embed_texts_for_search
from assistant.repositories.help_passages import HelpPassageRepository
from assistant.services.help_center_service import HelpCenterService

from assistant.clients.ledger import LedgerClient
from assistant.services.agent import ToolRound, ToolStarted, run_agent
from assistant.tools.base import ProposalSaver, ToolContext, HandoffRecorder, HelpSearcher
from assistant.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


# Reads the system prompt file the first time it is needed, then reuses it
@lru_cache
def system_prompt() -> str:
    return (Path(__file__).parent.parent / "prompts" / "system.md").read_text()


# All the chat logic. It knows nothing about HTTP: routers call it, it calls the repository
# and the model. "repo" is this request's repository; "ledger" makes calls to ledger-core as this
# caller; "registry" is the shared tool menu; "session_factory" opens a fresh database session
# for work that outlives the request (saving after a stream ends).
class ChatService:
    def __init__(
        self,
        repo: MessageRepository,
        ledger: LedgerClient,
        registry: ToolRegistry,
        router: ToolRouter,
        session_factory: Callable[[], Session] = new_session,
    ):
        self.repo = repo
        self.ledger = ledger
        self.registry = registry
        self.router = router
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

        # Proposals the tools save during this reply. They are announced to the app after each round.
        created_proposals: list[ProposalOut] = []
        context = ToolContext(
            self.ledger,
            self._proposal_saver(session_id, owner, created_proposals),
            self._handoff_function_for_tools(session_id, owner),
            self._help_search_function_for_tools(),
        )

        parts = []
        # Each round of lookups the agent reports. Saved with the reply so later turns know the real ids.
        rounds = []
        try:
            # run_agent reports three kinds of event: words for the customer, "a tool is running", and a finished round of lookups
            # Offer the model only the tools this message needs (falls back to all of them)
            registry = await self.router.registry_for_message(messages, self.registry)
            async for event in run_agent(messages, registry, context):
                if isinstance(event, ToolStarted):
                    # Lets the app show "Checking your account…" while the tool works
                    yield sse("tool", {"name": event.name})
                elif isinstance(event, ToolRound):
                    # Not for the customer: kept so we can save it with the reply
                    rounds.append(event)
                    # Any proposal saved in this round: tell the app to show its approval sheet
                    for proposal in created_proposals:
                        yield sse("approval_required", proposal.model_dump(mode="json"))
                    created_proposals.clear()
                else:
                    parts.append(event.text)
                    yield sse("token", {"text": event.text})
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
            # asdict turns the dataclasses into plain dicts that json.dumps can store
            tool_trace_json=json.dumps([asdict(r) for r in rounds]),
        )
        # Save in a worker thread so the (blocking) database call doesn't freeze other streams
        await run_in_threadpool(self._save_reply, reply)

        # Save first, then say "done", so a client never hears "done" about an unsaved reply
        yield sse("done", {"message_id": message_id, "trace_id": trace_id})

    # Uses its OWN session: the request's session may already be closed when a stream ends
    def _save_reply(self, reply: Message) -> None:
        with self.session_factory() as db:
            MessageRepository(db).add(reply)

    # Builds the function the propose tools call to save a proposal. Like _save_reply it opens its
    # OWN database session, because the request's session may be closed while the reply streams.
    # "created" collects each saved proposal so stream_reply can tell the app about it.
    def _proposal_saver(self, session_id: str, owner: str, created: list[ProposalOut]) -> ProposalSaver:
        def save_proposal(kind, params, summary) -> ProposalOut:
            with self.session_factory() as db:
                service = ActionService(db, ActionRepository(db), AuditRepository(db), self.ledger)
                # Turned into its public form INSIDE the "with", while the session is still open
                proposal = ProposalOut.from_action(service.create_proposal(session_id, owner, kind, params, summary))
            created.append(proposal)
            return proposal

        return save_proposal

    # Builds the function the hand-off tool calls. Like _proposal_saver it opens its own database session,
    # so the tool never sees a database.
    def _handoff_function_for_tools(self, session_id: str, owner: str) -> HandoffRecorder:
        def hand_off_and_get_reference(reason: str) -> int:
            with self.session_factory() as db:
                service = ActionService(db, ActionRepository(db), AuditRepository(db), self.ledger)
                return service.record_handoff_with_reference_number(session_id, owner, reason)

        return hand_off_and_get_reference

    # Builds the function the help-center tool calls. Like the others it opens its own database session,
    # so the tool never sees a database. The session stays open while the question is embedded (a fraction of a second).
    def _help_search_function_for_tools(self) -> HelpSearcher:
        async def look_up_passages_for_question(question: str) -> list[dict]:
            with self.session_factory() as db:
                service = HelpCenterService(db, HelpPassageRepository(db), embed_texts_for_search)
                found = await service.find_relevant_passages(question)
            return [{"article": f.article, "heading": f.heading, "text": f.text, "source": f.source} for f in found]

        return look_up_passages_for_question

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
