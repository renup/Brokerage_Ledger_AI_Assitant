from sqlmodel import Session, SQLModel, create_engine

from assistant.config import settings

# The engine is the shared connection pool to the assistant's database. One per process.
engine = create_engine(
    settings.assistant_database_url,
    # SQLite normally insists one thread uses a connection. FastAPI may use a session
    # from different threads, so we relax that check. (It's a dict: key, colon, value.)
    connect_args={"check_same_thread": False},
)


def create_db_and_tables():
    # Creates the messages table if it doesn't exist yet
    SQLModel.metadata.create_all(engine)


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
