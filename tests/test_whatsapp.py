import hashlib
import hmac
import json

import httpx
import pytest
from backend.app import store, whatsapp
from backend.app.config import settings

from conftest import event_payload

WA = {"whatsapp_token": "test-token", "whatsapp_phone_id": "12345",
      "whatsapp_app_secret": "app-secret", "whatsapp_verify_token": "verify-me"}


@pytest.fixture
def graph(monkeypatch):
    """Connect WhatsApp to a fake Graph API; yields the list of requests it received."""
    for key, value in WA.items():
        object.__setattr__(settings, key, value)  # Settings is frozen
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["authorization"] == "Bearer test-token"
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "media-1"})
        body = json.loads(request.content)
        if body["to"].endswith("0000000"):
            return httpx.Response(400, json={"error": {"message": "Recipient not on WhatsApp"}})
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{body['to']}"}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(whatsapp.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    yield calls
    for key in WA:
        object.__setattr__(settings, key, "")


def _event_with_guests(client) -> int:
    event_id = client.post("/api/events", json=event_payload()).json()["event"]["id"]
    guests = [
        {"name": "Meera Iyer", "phone": "98200 11223"},
        {"name": "Tom", "phone": "+44 7700 900123"},
        {"name": "No Phone", "email": "np@example.com"},
        {"name": "Bad Number", "phone": "+91 90000 0000000"},
    ]
    assert client.patch(f"/api/events/{event_id}", json={"guest_list": guests}).status_code == 200
    return event_id


def test_not_connected_is_reported_and_503(client):
    assert client.get("/api/whatsapp/status").json() == {"connected": False}
    event_id = _event_with_guests(client)
    r = client.post(f"/api/events/{event_id}/whatsapp/invite", json={"message": "Hi {name}"})
    assert r.status_code == 503


def test_bulk_invite_sends_template_with_image_and_tracks_status(client, graph):
    event_id = _event_with_guests(client)
    client.post(f"/api/events/{event_id}/invite", json={"tone": "fun"})
    store.save_art(event_id, "0-poster", "image/jpeg", b"poster-bytes")
    r = client.post(f"/api/events/{event_id}/whatsapp/invite",
                    json={"message": "Hi {name}, come celebrate!", "country_code": "+91"})
    body = r.json()
    assert r.status_code == 200 and body["sent"] == 2 and body["failed"] == 1
    assert body["errors"] == ["Recipient not on WhatsApp"]
    sends = [json.loads(c.content) for c in graph if c.url.path.endswith("/messages")]
    to = sorted(s["to"] for s in sends)
    assert "919820011223" in to and "447700900123" in to  # local number got +91
    meera = next(s for s in sends if s["to"] == "919820011223")["template"]
    assert meera["name"] == "utsav_invite"
    assert meera["components"][0]["parameters"][0]["image"]["id"] == "media-1"
    assert meera["components"][1]["parameters"][1]["text"] == "Hi Meera, come celebrate!"
    statuses = [g.get("wa_status") for g in body["guest_list"]]
    assert statuses == ["sent", "sent", "", "failed"]
    # Re-sending skips guests already reached and retries the failed one.
    graph.clear()
    client.post(f"/api/events/{event_id}/whatsapp/invite", json={"message": "Hi {name}"})
    retried = [json.loads(c.content)["to"] for c in graph if c.url.path.endswith("/messages")]
    assert retried == ["91900000000000"]


def test_card_image_must_be_png(client, graph):
    event_id = _event_with_guests(client)
    r = client.post(f"/api/events/{event_id}/whatsapp/invite",
                    json={"message": "Hi", "image": "card", "card_png": "bm90LWEtcG5n"})
    assert r.status_code == 422


def _signed(body: dict) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    sig = hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
    return raw, {"x-hub-signature-256": f"sha256={sig}", "content-type": "application/json"}


def test_webhook_updates_delivery_and_rejects_forgeries(client, graph):
    event_id = _event_with_guests(client)
    client.post(f"/api/events/{event_id}/invite", json={"tone": "fun"})
    store.save_art(event_id, "0-poster", "image/jpeg", b"x")
    client.post(f"/api/events/{event_id}/whatsapp/invite", json={"message": "Hi {name}"})

    def receipt(status):
        return {"entry": [{"changes": [{"value": {"statuses": [
            {"id": "wamid.919820011223", "status": status}]}}]}]}

    raw, headers = _signed(receipt("read"))
    assert client.post("/api/whatsapp/webhook", content=raw, headers=headers).status_code == 200
    raw, headers = _signed(receipt("delivered"))  # late, out-of-order receipt
    client.post("/api/whatsapp/webhook", content=raw, headers=headers)
    guests = client.get(f"/api/events/{event_id}").json()["event"]["guest_list"]
    assert guests[0]["wa_status"] == "read"
    forged = client.post("/api/whatsapp/webhook", content=raw,
                         headers={"x-hub-signature-256": "sha256=00"})
    assert forged.status_code == 403


def test_webhook_verification_handshake(client, graph):
    ok = client.get("/api/whatsapp/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
    assert ok.text == "42"
    bad = client.get("/api/whatsapp/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"})
    assert bad.status_code == 403


def test_host_reminder_summarises_urgent_alerts(client, graph):
    event_id = client.post("/api/events", json=event_payload()).json()["event"]["id"]
    r = client.post(f"/api/events/{event_id}/whatsapp/remind", json={"phone": "+91 98200 11223"})
    assert r.status_code == 200 and r.json()["sent"] >= 1
    sent = json.loads(graph[-1].content)
    assert sent["template"]["name"] == "utsav_reminder" and sent["to"] == "919820011223"
    assert "\n" not in sent["template"]["components"][0]["parameters"][1]["text"]


def test_param_and_msisdn_helpers():
    assert whatsapp.param("a\n\nb    c") == "a b c"
    assert whatsapp.to_msisdn("098200 11223", "+91") == "919820011223"
    assert whatsapp.to_msisdn("+1 (415) 555-0100", "+91") == "14155550100"
