from functools import lru_cache

import httpx
from fastapi import Depends, Request
from sqlmodel import Session

from assistant.auth import get_bearer_token
from assistant.clients.ledger import LedgerClient
from assistant.database import get_db
from assistant.repositories.messages import MessageRepository
from assistant.services.chat_service import ChatService
from assistant.tools.read import READ_TOOLS
from assistant.tools.registry import ToolRegistry


# FastAPI builds these in a chain for each request: db -> repository, http + token -> ledger
# client, and then the service from all of them. Routers just ask for a ChatService; nothing
# creates sessions, repositories or clients by hand.
# In tests, any link in the chain can be swapped out (app.dependency_overrides).
def get_message_repo(db: Session = Depends(get_db)) -> MessageRepository:
    return MessageRepository(db)


# The shared connection pool created in main.py's lifespan
def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


# A LedgerClient for THIS request: the shared pool plus THIS caller's own token
def get_ledger_client(
    http: httpx.AsyncClient = Depends(get_http_client),
    token: str = Depends(get_bearer_token),
) -> LedgerClient:
    return LedgerClient(http, token)


# The tool menu is the same for every customer, so build it once and reuse it
@lru_cache
def get_tool_registry() -> ToolRegistry:
    return ToolRegistry(READ_TOOLS)


def get_chat_service(
    repo: MessageRepository = Depends(get_message_repo),
    ledger: LedgerClient = Depends(get_ledger_client),
    registry: ToolRegistry = Depends(get_tool_registry),
) -> ChatService:
    return ChatService(repo, ledger, registry)
