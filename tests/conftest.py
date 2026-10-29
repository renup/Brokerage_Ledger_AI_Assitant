import os

from dotenv import dotenv_values

# The tests run against REAL Postgres (the same engine as production), in separate
# "_test" databases, so your demo data in ledger_core / assistant is never touched.
# Passwords come from the environment (CI) or from .env (your machine).
# These must be set BEFORE the services are imported, because their settings and database
# engines are created at import time. Environment variables win over .env.
_env = {**dotenv_values(".env"), **os.environ}


def _test_url(role: str, password_key: str) -> str:
    return f"postgresql+psycopg://{role}:{_env[password_key]}@localhost:5432/{role}_test"


os.environ["DATABASE_URL"] = _test_url("ledger_core", "LEDGER_CORE_DB_PASSWORD")
os.environ["ASSISTANT_DATABASE_URL"] = _test_url("assistant", "ASSISTANT_DB_PASSWORD")
# A fixed secret so the tests don't depend on your .env file
os.environ["JWT_SECRET"] = "test-secret-not-for-real-use-0123456789"

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from ledger_core.main import app
from ledger_core.seed import seed


# Build the tables once per test run by applying the REAL migrations, so the tests also
# prove that the migrations produce a schema the code works with.
@pytest.fixture(scope="session", autouse=True)
def migrated_databases():
    for service in ("ledger_core", "assistant"):
        command.upgrade(Config(f"{service}/alembic.ini"), "head")


# A fixture is a setup function that tests can ask for by naming it as a parameter.
# autouse=True runs it before EVERY test, so each test starts from the same seeded data
# (important because some tests, like retry, change the data).
@pytest.fixture(autouse=True)
def fresh_database():
    seed()


# Gives a test a ready-to-use client that talks to the app in-memory (no server needed)
@pytest.fixture
def client():
    return TestClient(app)