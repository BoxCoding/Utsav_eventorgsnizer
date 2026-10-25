"""Reading a free-text brief, budget estimates from it, and re-planning."""

from backend.app import ai
from backend.main import app
from fastapi.testclient import TestClient
from tests.conftest import create_event, event_payload


def test_brief_offline_reading(client):
    r = client.post("/api/events/brief", json={
        "brief": "My daughter's 7th birthday party, about 40 people, budget around $3,000. "
                 "Lots of kids, two are vegan. Date 2099-05-04."})
    body = r.json()
    assert body["source"] == "offline"
    assert body["fields"] == {"kind": "birthday", "guests": 40, "budget": 3000,
                              "currency": "USD", "event_date": "2099-05-04"}
    titles = [t["title"] for t in body["custom_tasks"]]
    assert any("kids" in t for t in titles) and any("dietary" in t for t in titles)
    assert client.post("/api/events/brief", json={"brief": "short"}).status_code == 422


def test_brief_model_output_is_validated():
    from datetime import date as d
    raw = {"kind": "wedding", "guests": 120, "budget": "lots", "currency": "XYZ",
           "event_date": "2001-01-01", "custom_tasks": [
               {"title": "Book a mehndi artist", "category": "Attire & beauty", "lead_days": 40},
               {"title": "Hack", "category": "Nope", "lead_days": 1}],
           "split": {"Catering": 0.6}, "summary": ["Big wedding"]}
    out = ai._clean_brief(raw, d(2026, 1, 1))
    # unknown currency and past date are dropped; a bad budget becomes an explained estimate
    assert out["fields"] == {"kind": "wedding", "guests": 120, "budget": 480_000}
    assert out["budget_estimate"]["source"] == "utsav"
    assert [t["title"] for t in out["custom_tasks"]] == ["Book a mehndi artist"]
    assert abs(sum(out["split"].values()) - 1) < 0.001


def test_create_with_currency_brief_and_custom_tasks(client):
    body = create_event(client, currency="EUR", budget=40_000, brief="Garden wedding, vegan menu",
                   custom_tasks=[{"title": "Confirm vegan menu", "category": "Catering",
                                  "lead_days": 20},
                                 {"title": "Sneaky", "category": "Not real", "lead_days": 5}],
                   split_override={"Catering": 0.5, "Bogus": 1})
    assert body["event"]["currency"] == "EUR" and body["plan"]["budget"]["currency"] == "EUR"
    assert [t["title"] for t in body["event"]["custom_tasks"]] == ["Confirm vegan menu"]
    assert "Bogus" not in body["event"]["split_override"]
    ask = client.post(f"/api/events/{body['event']['id']}/ask", json={"question": "budget?"})
    assert "€40,000" in ask.json()["answer"]
    bad = client.post("/api/events", json=event_payload(currency="XXX"))
    assert bad.status_code == 422


def test_replan_from_edited_brief(client):
    body = create_event(client, kind="birthday", budget=60_000, guests=40, custom_tasks=[
        {"title": "Book a magician", "category": "Entertainment", "lead_days": 20},
        {"title": "Order a dinosaur cake", "category": "Food & cake", "lead_days": 10}])
    event_id = body["event"]["id"]
    client.patch(f"/api/events/{event_id}", json={"done": ["c-book-a-magician",
                                                           "c-order-a-dinosaur-cake"]})
    # The re-read keeps the event's type even if the text sounds like something else.
    preview = client.post("/api/events/brief", json={
        "brief": "Actually a big community fair feel, 60 people, two kids are vegan",
        "kind": "birthday"}).json()
    assert preview["fields"]["kind"] == "birthday" and preview["fields"]["guests"] == 60
    tasks = [{"title": "Book a magician", "category": "Entertainment", "lead_days": 20},
             *preview["custom_tasks"]]
    r = client.patch(f"/api/events/{event_id}", json={
        "brief": "Actually a big community fair feel...", "guests": 60, "custom_tasks": tasks,
        "split_override": {"Entertainment": 0.4}})
    event = r.json()["event"]
    assert event["guests"] == 60 and event["brief"].startswith("Actually")
    assert "c-book-a-magician" in event["done"]           # surviving task keeps its tick
    assert "c-order-a-dinosaur-cake" not in event["done"]  # removed task's tick dropped
    assert abs(sum(event["split_override"].values()) - 1) < 0.001


def test_replan_endpoint_is_owned_and_pins_kind(client, monkeypatch):
    seen = {}

    async def fake_json(prompt, system=None, **_):
        seen["system"] = system
        return {"kind": "community", "guests": 80, "custom_tasks": [], "summary": ["ok"]}

    monkeypatch.setattr(ai.gemini_client, "generate_json", fake_json)
    event_id = create_event(client, kind="birthday", budget=60_000, guests=40)["event"]["id"]
    r = client.post(f"/api/events/{event_id}/replan", json={"brief": "Now 80 guests, same party"})
    assert r.json()["fields"]["kind"] == "birthday" and r.json()["fields"]["guests"] == 80
    assert "RE-PLAN" in seen["system"] and '"guests": 40' in seen["system"]
    other = TestClient(app)
    other.post("/api/auth/register",
               json={"name": "Z", "email": "z@example.com", "password": "s3cret-pass"})
    assert other.post(f"/api/events/{event_id}/replan",
                      json={"brief": "Now 80 guests, same party"}).status_code == 404


def test_brief_details_never_put_a_date_in_the_time_box():
    merged = ai._merge_details({"tone": "fun", "host": "", "venue": "", "time": "", "rsvp": ""},
                               {"details": {"time": "Thursday, 29 October 2026", "venue": "Lawn"}})
    assert merged["time"] == "" and merged["venue"] == "Lawn"
    ok = ai._merge_details({"time": ""}, {"details": {"time": "6:30 pm onwards"}})
    assert ok["time"] == "6:30 pm onwards"


def test_brief_budget_estimate_is_validated(monkeypatch):
    from datetime import date as d
    base = {"kind": "community", "guests": 400, "summary": ["x"]}
    ok = ai._clean_brief({**base, "budget_estimate": 150_000, "budget_reasoning": "Food for 400"},
                         d(2026, 1, 1))
    assert ok["fields"]["budget"] == 150_000 and ok["budget_estimate"]["source"] == "gemini"
    absurd = ai._clean_brief({**base, "budget_estimate": 99}, d(2026, 1, 1))
    assert absurd["budget_estimate"]["source"] == "utsav"  # rule-based, explained
    assert absurd["fields"]["budget"] == 130_000
    assert "400 guests" in absurd["budget_estimate"]["reasoning"]
    stated = ai._clean_brief({**base, "budget": 240_000, "budget_estimate": 1}, d(2026, 1, 1))
    assert stated["fields"]["budget"] == 240_000 and stated["budget_estimate"] is None
