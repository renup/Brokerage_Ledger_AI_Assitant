from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from assistant.auth import customer_hash, get_current_user
from assistant.dependencies import get_chat_service
from assistant.schemas import ChatRequest, FeedbackRequest, FeedbackResponse
from assistant.services.chat_service import ChatService

router = APIRouter(tags=["chat"])


# Plain "def" on purpose: FastAPI runs it in a worker thread, so its database calls don't
# block other requests. The returned stream is still async and runs on the event loop.
@router.post("/chat")
def chat(
    body: ChatRequest,
    # Runs first: a bad token gets a 401 and this function never runs.
    # "user" is what ledger-core returned for /me.
    user: dict = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    owner = customer_hash(user["id"])
    # "Maya Patel".split()[0] picks the first word: "Maya"
    first_name = user["name"].split()[0]
    messages = service.prepare_turn(body.session_id, owner, first_name, body.message)
    # StreamingResponse sends each yielded piece as soon as it exists,
    # instead of waiting for the whole reply.
    return StreamingResponse(
        service.stream_reply(messages, body.session_id, owner),
        # This content type tells clients "this is an SSE stream"
        media_type="text/event-stream",
        # Tells browsers and proxies not to hold the stream back in a cache
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/chat/{session_id}/feedback", response_model=FeedbackResponse)
def feedback(
    session_id: str,
    body: FeedbackRequest,
    user: dict = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    service.rate_reply(session_id, body.message_id, customer_hash(user["id"]), body.rating)
    return FeedbackResponse(ok=True)
