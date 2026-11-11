import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from assistant.config import settings
from assistant.errors import NotFoundError, ActionAlreadyDecidedError, ActionExpiredError
from assistant.routers import chat, health, sessions, actions
from assistant.services.model_readiness import get_models_ready_for_first_customer


# "lifespan" runs code once when the server starts (before "yield") and once when it stops.
# We create ONE connection pool to ledger-core here and share it with every request.
# Opening a new connection for each call is slow; a shared pool reuses them.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # base_url means calls elsewhere can use short paths like "/me/accounts"
    async with httpx.AsyncClient(base_url=settings.ledger_core_url) as http:
        # app.state is a place to keep things that live as long as the server does
        app.state.http = http
        # In the background (a task), so the server answers requests while the models load. We keep the task in a
        # variable so it is not garbage-collected half way, and cancel it if the server stops first.
        warm_up = asyncio.create_task(get_models_ready_for_first_customer())
        yield
        warm_up.cancel()
    # Leaving the "async with" block closes the pool cleanly at shutdown


app = FastAPI(title="assistant", lifespan=lifespan)


# The one place a domain NotFoundError becomes an HTTP 404, so routers and services never repeat it
@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})

# 410 Gone: it existed, but its 24 hours are over
@app.exception_handler(ActionExpiredError)
async def action_expired_handler(request: Request, exc: ActionExpiredError):
    return JSONResponse(status_code=410, content={"detail": str(exc)})

# 409 Conflict: already approved, rejected or finished (also what the loser of a double tap gets)
@app.exception_handler(ActionAlreadyDecidedError)
async def action_already_decided_handler(request: Request, exc: ActionAlreadyDecidedError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


app.include_router(health.router)
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(actions.router)
