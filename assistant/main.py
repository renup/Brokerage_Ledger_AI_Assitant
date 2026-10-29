from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from assistant.database import create_db_and_tables
from assistant.errors import NotFoundError
from assistant.routers import chat, health, sessions


# "lifespan" runs code once when the server starts (before "yield") and once when it stops.
# We use it to create the messages table on startup.
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(title="assistant", lifespan=lifespan)


# The one place a domain NotFoundError becomes an HTTP 404, so routers and services never repeat it
@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


app.include_router(health.router)
app.include_router(chat.router)
app.include_router(sessions.router)
