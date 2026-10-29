from fastapi import Depends
from sqlmodel import Session

from assistant.database import get_db
from assistant.repositories.messages import MessageRepository
from assistant.services.chat_service import ChatService


# FastAPI builds these in a chain for each request: db -> repository -> service.
# Routers just ask for a ChatService; nothing creates sessions or repositories by hand.
# In tests, any link in the chain can be swapped out (app.dependency_overrides).
def get_message_repo(db: Session = Depends(get_db)) -> MessageRepository:
    return MessageRepository(db)


def get_chat_service(repo: MessageRepository = Depends(get_message_repo)) -> ChatService:
    return ChatService(repo)
