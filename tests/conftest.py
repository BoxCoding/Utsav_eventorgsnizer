import os
import tempfile

# Configure before the app is imported: isolated DB, no network calls to Gemini.
os.environ["UTSAV_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["UTSAV_OFFLINE"] = "1"

import itertools
from datetime import date, timedelta

import pytest
from backend.main import app
from fastapi.testclient import TestClient

_ids = itertools.count()


@pytest.fixture
def client() -> TestClient:
    """A signed-in client with a fresh, unique account."""
    c = TestClient(app)
    n = next(_ids)
    r = c.post(
        "/api/auth/register",
        json={"name": f"User {n}", "email": f"user{n}@example.com", "password": "s3cret-pass"},
    )
    assert r.status_code == 201
    return c


def event_payload(**overrides) -> dict:
    return {
        "name": "Asha & Rohan",
        "kind": "wedding",
        "event_date": (date.today() + timedelta(days=200)).isoformat(),
        "guests": 200,
        "budget": 1_500_000,
        "city": "Jaipur",
        "vibe": "royal, warm",
        "tradition": "Marwari",
        **overrides,
    }
