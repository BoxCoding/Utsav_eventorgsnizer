"""Event CRUD, the computed plan, budgets, guests and notifications."""
from datetime import date, timedelta

from backend.app import ai
from backend.main import app
from fastapi.testclient import TestClient
from tests.conftest import create_event, event_payload


def test_create_returns_full_plan(client):
    body = create_event(client)
    assert body["event"]["name"] == "Asha & Rohan"
    assert body["plan"]["budget"]["total"] == 1_500_000
    assert sum(line["planned"] for line in body["plan"]["budget"]["lines"]) == 1_500_000
    assert body["plan"]["days_left"] == 200
    assert client.get("/api/events").json()["events"][0]["id"] == body["event"]["id"]


def test_rejects_invalid_events(client):
    past = (date.today() - timedelta(days=1)).isoformat()
    assert client.post("/api/events", json=event_payload(event_date=past)).status_code == 422
    assert client.post("/api/events", json=event_payload(kind="funeral")).status_code == 422
    assert client.post("/api/events", json=event_payload(guests=0)).status_code == 422


def test_patch_checklist_spend_and_what_if(client):
    event_id = create_event(client)["event"]["id"]
    r = client.patch(
        f"/api/events/{event_id}",
        json={
            "done": ["shortlist-and-book-the-venue", "not-a-real-task"],
            "spend": {"Venue": 300_000, "Hacked": 1},
            "guests": 1000,
        },
    )
    body = r.json()
    assert body["event"]["done"] == ["shortlist-and-book-the-venue"]
    assert body["event"]["spend"] == {"Venue": 300_000}
    assert body["plan"]["budget"]["spent"] == 300_000
    assert body["plan"]["health"]["label"] != "On track"  # ₹1,500/guest is thin for 1000
    neg = client.patch(f"/api/events/{event_id}", json={"spend": {"Venue": -5}})
    assert neg.status_code == 422


def test_calendar_export(client):
    event_id = create_event(client)["event"]["id"]
    r = client.get(f"/api/events/{event_id}/calendar.ics")
    assert r.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in r.text


def test_delete_event(client):
    event_id = create_event(client)["event"]["id"]
    assert client.delete(f"/api/events/{event_id}").status_code == 204
    assert client.get(f"/api/events/{event_id}").status_code == 404


def test_notifications_endpoint_aggregates_user_events(client):
    soon = (date.today() + timedelta(days=3)).isoformat()
    create_event(client, kind="birthday", event_date=soon, budget=20_000, guests=50)
    notes = client.get("/api/notifications").json()["notifications"]
    assert notes and notes[0]["priority"] == "critical"
    fields = {"id", "event_id", "event_name", "priority", "title", "message", "tab"}
    assert fields <= notes[0].keys()
    assert TestClient(app).get("/api/notifications").status_code == 401


def test_guest_list_saved_and_validated(client):
    event_id = create_event(client)["event"]["id"]
    guests = [
        {"name": "Meera", "email": "meera@example.com"},
        {"name": "Raj", "phone": "+91 98765 43210"},
    ]
    body = client.patch(f"/api/events/{event_id}", json={"guest_list": guests}).json()
    assert [g["name"] for g in body["event"]["guest_list"]] == ["Meera", "Raj"]
    bad_list = [{"name": "X", "email": "nope"}]
    bad = client.patch(f"/api/events/{event_id}", json={"guest_list": bad_list})
    assert bad.status_code == 422


def test_event_specific_categories_skips_and_spend_pruning(client):
    cats = {"Food & prasad": 0.5, "Puja samagri": 0.2, "Mehndi artists": 0.15,
            "Decor & lighting": 0.1, "Contingency": 0.05}
    body = create_event(client, kind="community", budget=240_000, guests=400, split_override=cats,
                   skipped=["book-the-ground-or-hall", "not-a-task"],
                   custom_tasks=[{"title": "Order puja thalis", "category": "Puja samagri",
                                  "lead_days": 10},
                                 {"title": "Hire DJ", "category": "Sound & stage",
                                  "lead_days": 10}])
    event, plan = body["event"], body["plan"]
    assert [ln["category"] for ln in plan["budget"]["lines"]] == list(cats)
    assert event["skipped"] == ["book-the-ground-or-hall"]
    assert [t["title"] for t in event["custom_tasks"]] == ["Order puja thalis"]  # unknown category
    event_id = event["id"]
    client.patch(f"/api/events/{event_id}", json={"spend": {"Puja samagri": 9000,
                                                            "Food & prasad": 50000}})
    # Re-plan drops "Puja samagri": its spend goes, the rest stays.
    r = client.patch(f"/api/events/{event_id}", json={"split_override": {
        "Food & prasad": 0.6, "Mehndi artists": 0.2, "Decor & lighting": 0.15,
        "Contingency": 0.05}})
    assert r.json()["event"]["spend"] == {"Food & prasad": 50000}


def test_full_ai_checklist_replaces_standard_tasks(client):
    cats = {"Food & prasad": 0.5, "Puja samagri": 0.2, "Mehndi artists": 0.15,
            "Decor & lighting": 0.1, "Contingency": 0.05}
    raw = {"kind": "community", "split": cats, "custom_tasks": [
        {"title": f"Task {i}", "category": "Planning" if i % 2 else "Food & prasad",
         "lead_days": 20 - i} for i in range(10)], "summary": ["x"]}
    out = ai._clean_brief(raw, date(2026, 1, 1))
    assert len(out["custom_tasks"]) == 10 and len(out["skipped"]) == 12  # all standard tasks
    body = create_event(client, kind="community", split_override=cats,
                   custom_tasks=out["custom_tasks"], skipped=out["skipped"])
    plan = body["plan"]
    assert plan["ai_checklist"] and len(plan["tasks"]) == 10
    assert {t["category"] for t in plan["tasks"]} == {"Planning", "Food & prasad"}
    assert [ln["category"] for ln in plan["budget"]["lines"]] == list(cats)  # no Planning line


def test_blank_budget_is_estimated_not_defaulted(client):
    payload = event_payload(kind="birthday", guests=40)
    payload.pop("budget")
    event = client.post("/api/events", json=payload).json()["event"]
    assert event["budget"] == 38_000  # 40 guests x ₹600 floor x 1.6 comfort, 2 sig. figures
    assert "Estimated by Utsav" in event["budget_note"]


def test_estimate_endpoint_validates_budgets(client):
    q = "/api/events/estimate?kind=wedding&guests=200&currency=INR"
    assert client.get(q).json()["verdict"] == "missing"
    assert client.get(q + "&budget=100000").json()["verdict"] == "too-low"   # ₹500/guest
    assert client.get(q + "&budget=400000").json()["verdict"] == "tight"     # ₹2,000
    assert client.get(q + "&budget=1200000").json()["verdict"] == "comfortable"
    assert client.get(q + "&budget=5000000").json()["verdict"] == "generous"
    assert client.get(q.replace("200", "0")).status_code == 422


def test_blank_guest_names_are_rejected(client):
    event_id = create_event(client)["event"]["id"]
    blank = [{"name": "   ", "phone": "+91 98200 11223"}]
    r = client.patch(f"/api/events/{event_id}", json={"guest_list": blank})
    assert r.status_code == 422
    ok = client.patch(f"/api/events/{event_id}", json={"guest_list": [{"name": "  Meera  "}]})
    assert ok.json()["event"]["guest_list"][0]["name"] == "Meera"
