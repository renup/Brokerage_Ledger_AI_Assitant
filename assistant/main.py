from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from assistant.errors import NotFoundError
from assistant.routers import chat, health, sessions


app = FastAPI(title="assistant")


# The one place a domain NotFoundError becomes an HTTP 404, so routers and services never repeat it
@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


app.include_router(health.router)
app.include_router(chat.router)
app.include_router(sessions.router)
