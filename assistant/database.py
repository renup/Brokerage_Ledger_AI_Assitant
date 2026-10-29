from sqlmodel import Session, SQLModel, create_engine

from assistant.config import settings

# The engine is the shared connection to the assistant's database file
engine = create_engine(
    settings.assistant_database_url,
    # SQLite normally insists one thread uses a connection. FastAPI may use a session
    # from different threads, so we relax that check. (It's a dict: key, colon, value.)
    connect_args={"check_same_thread": False},
)


def create_db_and_tables():
    # Creates the messages table if it doesn't exist yet
    SQLModel.metadata.create_all(engine)


def get_session():
    # One conversation with the database per request, closed automatically afterwards
    with Session(engine) as session:
        yield session
