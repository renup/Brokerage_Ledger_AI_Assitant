from sqlmodel import Session, create_engine

from assistant.config import settings

# The engine is the shared pool of database connections, one per process.
# pool_pre_ping=True tests a pooled connection with a tiny query before using it, so a
# connection that Postgres closed (restart, idle timeout) is replaced instead of causing an error.
engine = create_engine(settings.assistant_database_url, pool_pre_ping=True)


# The tables are created and changed by Alembic migrations (assistant/migrations),
# never by the app at startup.


# Opens a new database session. This is the "session factory": code that outlives a
# request (like a streaming reply) calls it to get its OWN session instead of borrowing
# the request's, which may already be closed by then.
def new_session() -> Session:
    return Session(engine)


# FastAPI dependency: one database session per request, closed automatically afterwards.
# Named "db" everywhere so it is never confused with a chat "session_id".
def get_db():
    with new_session() as db:
        yield db
