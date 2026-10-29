import asyncio
import json
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from assistant.auth import customer_hash, get_current_user
from assistant.database import create_db_and_tables, engine, get_session
from assistant.models import Message
from assistant.schemas import ChatRequest, MessageOut, FeedbackRequest, FeedbackResponse

# The fixed reply for now. The greeting with the customer's name goes in front of it.
# In Phase 4, a real AI model replaces this.
CANNED_REPLY = "I am Ask Ledger. I cannot look at your account yet, but I am learning"


# "lifespan" runs code once when the server starts (before "yield") and once when it stops.
# We use it to create the messages table on startup.
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(title="assistant", lifespan=lifespan)


# Formats one SSE message: "event: <name>", "data: <json>", then a BLANK line to end it
def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# Streams the reply word by word, then saves it. "async def" because of "await" below.
async def reply_stream(first_name: str, session_id: str, owner: str):
    reply = f"Hi {first_name}! {CANNED_REPLY}"
    # Ids for this reply, sent to the client in the final "done" message
    message_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())

    for word in reply.split():
        # Add the space back, because split() removed it
        yield sse("token", {"text": word + " "})
        # Pause so the words visibly arrive one at a time
        await asyncio.sleep(0.2)

    # Save the finished reply. We open our OWN session here, because the request's
    # session may already be closed by the time the stream finishes.
    with Session(engine) as session:
        session.add(
            Message(
                message_id=message_id,
                session_id=session_id,
                customer_id_hash=owner,
                role="assistant",
                text=reply,
                trace_id=trace_id,
            )
        )
        session.commit()

    # Save first, then say "done", so a client never hears "done" about an unsaved reply
    yield sse("done", {"message_id": message_id, "trace_id": trace_id})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
async def chat(
    body: ChatRequest,
    # Runs first: a bad token gets a 401 and this function never runs.
    # "user" is what ledger-core returned for /me.
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    owner = customer_hash(user["id"])

    # Is this session id already used by a DIFFERENT customer? If so, refuse with 404,
    # the same trick as before: don't reveal that someone else's session exists.
    taken = session.exec(
        select(Message).where(Message.session_id == body.session_id, Message.customer_id_hash != owner)
    ).first()
    if taken is not None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Save the customer's message before replying
    session.add(
        Message(
            message_id=str(uuid.uuid4()),
            session_id=body.session_id,
            customer_id_hash=owner,
            role="user",
            text=body.message,
        )
    )
    session.commit()

    # StreamingResponse sends each yielded piece as soon as it exists,
    # instead of waiting for the whole reply.
    return StreamingResponse(
        # "Maya Patel".split()[0] picks the first word: "Maya"
        reply_stream(user["name"].split()[0], body.session_id, owner),
        # This content type tells clients "this is an SSE stream"
        media_type="text/event-stream",
        # Tells browsers and proxies not to hold the stream back in a cache
        headers={"Cache-Control": "no-cache"},
    )


# Full conversation history. Plain "def" because it never waits on anything slow.
@app.get("/sessions/{session_id}", response_model=list[MessageOut])
def session_history(
    session_id: str,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    owner = customer_hash(user["id"])
    messages = session.exec(
        select(Message)
        # Both conditions: the right session AND the right owner
        .where(Message.session_id == session_id, Message.customer_id_hash == owner)
        # Oldest first, like reading a chat
        .order_by(Message.created_at)
    ).all()
    # Empty means "no such session, or not yours". Same 404 for both.
    if not messages:
        raise HTTPException(status_code=404, detail="Session not found")
    return [
        MessageOut(
            message_id=m.message_id,
            role=m.role,
            text=m.text,
            # Turn the stored JSON text back into a list
            sources=json.loads(m.sources_json),
            ts=m.created_at,
        )
        for m in messages
    ]

# Plain "def": it only does a quick database update, nothing slow.
# {session_id} in the path is a path parameter, like {transfer_id} in ledger-core.
@app.post("/chat/{session_id}/feedback", response_model=FeedbackResponse)
def feedback(
    session_id: str,
    body: FeedbackRequest,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    owner = customer_hash(user["id"])

    # Find the one message being rated. ALL four conditions must hold.
    message = session.exec(
        select(Message)
        .where(
            # the message the caller named...
            Message.message_id == body.message_id,
            # ...in the session named in the URL...
            Message.session_id == session_id,
            # ...belonging to this customer (so you can't rate someone else's chat)...
            Message.customer_id_hash == owner,
            # ...and written by the assistant (you rate replies, not your own words)
            Message.role == "assistant"
        )
    ).first()

    # No match for any reason gives the same 404, so nothing is revealed about
    # messages that belong to other people
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    # Save the rating on the existing row. Rating again simply replaces the old one.
    message.rating = body.rating
    session.add(message)
    session.commit()
    return FeedbackResponse(ok=True)

