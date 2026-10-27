import os
import tempfile

# These must be set BEFORE ledger_core is imported, because the database engine
# and settings are created at import time. Environment variables win over .env.
# The tests get their own throwaway database file, so your real ledger.db is never touched.
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test_ledger.db"
# A fixed secret so the tests don't depend on your .env file
os.environ["JWT_SECRET"] = "test-secret-not-for-real-use-0123456789"

import pytest
from fastapi.testclient import TestClient

from ledger_core.main import app
from ledger_core.seed import seed


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