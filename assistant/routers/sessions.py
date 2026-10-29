from fastapi import APIRouter, Depends

from assistant.auth import customer_hash, get_current_user
from assistant.dependencies import get_chat_service
from assistant.schemas import MessageOut
from assistant.services.chat_service import ChatService

router = APIRouter(tags=["sessions"])


# Full conversation history, oldest first, like reading a chat
@router.get("/sessions/{session_id}", response_model=list[MessageOut])
def session_history(
    session_id: str,
    user: dict = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    messages = service.get_history(session_id, customer_hash(user["id"]))
    return [MessageOut.from_message(m) for m in messages]
