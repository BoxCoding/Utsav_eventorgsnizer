import os
import tempfile

# Configure before the app is imported: isolated DB, no network calls to Gemini.
os.environ["UTSAV_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["UTSAV_OFFLINE"] = "1"

# UTSAV_STORE=firestore runs the same suite against the Firestore emulator
# (FIRESTORE_EMULATOR_HOST must point at it); wipe it so every run starts empty.
if os.environ.get("UTSAV_STORE") == "firestore":
    import urllib.request

    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "utsav-test")
    urllib.request.urlopen(urllib.request.Request(
        f"http://{os.environ['FIRESTORE_EMULATOR_HOST']}/emulator/v1/projects/"
        f"{os.environ['GOOGLE_CLOUD_PROJECT']}/databases/(default)/documents", method="DELETE"))

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


def create_event(client, **kw) -> dict:
    """Create an event through the API and return its {event, plan} view."""
    r = client.post("/api/events", json=event_payload(**kw))
    assert r.status_code == 201, r.text
    return r.json()
