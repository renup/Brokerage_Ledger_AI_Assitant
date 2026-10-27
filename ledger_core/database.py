from sqlmodel import SQLModel, Session, create_engine

from ledger_core.config import settings

# The engine is the shared connection to the database.
# It doesn't touch the file until the first query.
engine = create_engine(settings.database_url)


def create_db_and_tables():
    # Creates a real table for every model class (table=True) that has been
    # imported. Tables that already exist are skipped.
    SQLModel.metadata.create_all(engine)


def get_session():
    # A session is one "conversation" with the database.
    # The with-block closes it automatically, even if an error happens.
    with Session(engine) as session:
        # yield hands the session to the endpoint and pauses here.
        # When the request finishes, the function resumes and the with-block cleans up.
        yield session
