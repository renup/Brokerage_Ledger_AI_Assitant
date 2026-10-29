from sqlmodel import Session, create_engine

from ledger_core.config import settings

# The engine is the shared pool of database connections, one per process.
# It doesn't connect until the first query.
# pool_pre_ping=True tests a pooled connection with a tiny query before using it, so a
# connection that Postgres closed (restart, idle timeout) is replaced instead of causing an error.
engine = create_engine(settings.database_url, pool_pre_ping=True)


# The tables themselves are created and changed by Alembic migrations (ledger_core/migrations),
# never by the app at startup, so a schema change is always a reviewed, versioned file.
def get_session():
    # A session is one "conversation" with the database.
    # The with-block closes it automatically, even if an error happens.
    with Session(engine) as session:
        # yield hands the session to the endpoint and pauses here.
        # When the request finishes, the function resumes and the with-block cleans up.
        yield session
