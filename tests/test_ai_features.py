"""Ideas, Ask Utsav, run sheets and smart alerts: Gemini path, validation, fallbacks."""
from datetime import date, timedelta

from backend.app import ai
from backend.main import app
from fastapi.testclient import TestClient
from tests.conftest import create_event


def test_ideas_fall_back_offline_and_are_cached(client):
    event_id = create_event(client, kind="birthday", budget=60_000, guests=40)["event"]["id"]
    ideas = client.post(f"/api/events/{event_id}/ideas").json()["ideas"]
    assert ideas["source"] == "offline"
    assert ideas["decor"] and ideas["palette"]
    assert "marwari" in ideas["tagline"].lower()
    assert client.get(f"/api/events/{event_id}").json()["event"]["ideas"] == ideas


def test_ask_is_grounded_in_plan(client):
    event_id = create_event(client)["event"]["id"]
    r = client.post(f"/api/events/{event_id}/ask", json={"question": "How is my budget?"})
    body = r.json()
    assert body["source"] == "offline"
    assert "₹15,00,000" in body["answer"]
    nxt = client.post(f"/api/events/{event_id}/ask", json={"question": "What next?"}).json()
    assert "Next up" in nxt["answer"]
    long = client.post(f"/api/events/{event_id}/ask", json={"question": "x" * 501})
    assert long.status_code == 422


def test_model_output_is_validated():
    clean = ai._clean_ideas(
        {"theme": "T", "palette": ["#ffffff", "red", "javascript:"], "decor": ["a", "", 3]}
    )
    assert clean["palette"] == ["#ffffff"]
    assert clean["decor"] == ["a", "3"]
    for bad in (None, {"decor": ["x"]}, {"theme": "T", "decor": []}):
        try:
            ai._clean_ideas(bad)
        except ai.LLMUnavailableError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_gemini_path_used_when_available(client, monkeypatch):
    async def fake_json(prompt, system=None, **_):
        assert "<event>" in prompt and "Never mention prices" in system
        return {"theme": "Rajputana Rose", "palette": ["#9f1239"], "decor": ["Jharokha arches"]}

    monkeypatch.setattr(ai.gemini_client, "generate_json", fake_json)
    event_id = create_event(client)["event"]["id"]
    ideas = client.post(f"/api/events/{event_id}/ideas").json()["ideas"]
    assert ideas["source"] == "gemini" and ideas["theme"] == "Rajputana Rose"


def test_run_sheet_offline_saved_and_owned(client):
    event_id = create_event(client)["event"]["id"]
    sheet = client.post(f"/api/events/{event_id}/runsheet").json()["run_sheet"]
    assert sheet["source"] == "offline" and len(sheet["items"]) >= 5
    assert {"time", "title", "detail", "owner"} <= sheet["items"][0].keys()
    assert client.get(f"/api/events/{event_id}").json()["event"]["run_sheet"] == sheet
    other = TestClient(app)
    other.post("/api/auth/register",
               json={"name": "R", "email": "r@example.com", "password": "s3cret-pass"})
    assert other.post(f"/api/events/{event_id}/runsheet").status_code == 404


def test_run_sheet_model_output_is_validated():
    good = {"items": [{"time": "~20:15", "title": "Moonrise and argh", "detail": "x" * 300,
                       "owner": "Volunteers"}] * 4}
    items = ai._clean_run_sheet(good)
    assert len(items) == 4 and len(items[0]["detail"]) == 160
    for bad in (None, {"items": []}, {"items": [{"title": ""}] * 5}):
        try:
            ai._clean_run_sheet(bad)
        except ai.LLMUnavailableError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_ideas_and_invites_are_built_from_the_brief(client, monkeypatch):
    prompts = []

    async def fake_json(prompt, system=None, **_):
        prompts.append((prompt, system))
        if "invitation" in system:
            concept = {**{k: "x" for k in ai.COPY_LIMITS}, "hashtag": "#KC",
                       "design": {"layout": "framed", "type": "serif", "palette": ["#112233"],
                                  "art_prompt": "lotus", "text_tone": "dark"}}
            return {"details": {"host": "Ladies' committee", "venue": "Clubhouse", "time": "",
                                "rsvp": "Sign-up sheet"}, "concepts": [concept]}
        return {"theme": "Chandni Raat", "palette": ["#112233"], "decor": ["Diyas"]}

    monkeypatch.setattr(ai.gemini_client, "generate_json", fake_json)
    brief = "Karwa Chauth for 400 residents in our society clubhouse, puja then terrace argh"
    event_id = create_event(client, kind="community", brief=brief)["event"]["id"]
    client.post(f"/api/events/{event_id}/ideas")
    invite = client.post(f"/api/events/{event_id}/invite",
                         json={"tone": "elegant", "rsvp": "Call Neha"}).json()["invite"]
    ideas_prompt, ideas_system = prompts[0]
    assert "terrace argh" in ideas_prompt and "most important" in ideas_system
    assert '"budget_categories"' in ideas_prompt
    assert "terrace argh" in prompts[1][0]
    # empty boxes filled from the brief; what the user typed wins
    assert invite["details"]["venue"] == "Clubhouse" and invite["details"]["rsvp"] == "Call Neha"
    assert invite["details"]["host"] == "Ladies' committee" and invite["details"]["time"] == ""


def test_ask_uses_brief_run_sheet_and_invite_details(client, monkeypatch):
    seen = {}

    async def fake_text(prompt, system=None, history=None, temperature=None):
        seen["prompt"], seen["system"] = prompt, system
        return "The puja is in the clubhouse."

    monkeypatch.setattr(ai.gemini_client, "generate_text", fake_text)
    brief = "Karwa Chauth: puja in the clubhouse, argh on the Tower 6 terrace"
    event_id = create_event(client, kind="community", brief=brief)["event"]["id"]
    client.post(f"/api/events/{event_id}/runsheet")  # offline skeleton is fine here
    r = client.post(f"/api/events/{event_id}/ask", json={"question": "Where is the puja?"})
    assert r.json()["source"] == "gemini"
    assert "Tower 6 terrace" in seen["prompt"] and '"run_sheet"' in seen["prompt"]
    assert "host's own description" in seen["system"]


def test_brief_alerts_endpoint(client, monkeypatch):
    async def fake_json(prompt, system=None, **_):
        assert "reminder engine" in system and "residents" in prompt
        return {"alerts": [{"title": "Collect contributions", "message": "From each flat.",
                            "priority": "urgent!", "days_before": 30, "tab": "nowhere"}]}

    monkeypatch.setattr(ai.gemini_client, "generate_json", fake_json)
    soon = (date.today() + timedelta(days=10)).isoformat()
    event_id = create_event(client, kind="community", event_date=soon,
                       brief="Festival for residents, collect money from each flat")["event"]["id"]
    alerts = client.post(f"/api/events/{event_id}/alerts").json()["brief_alerts"]
    assert alerts["items"][0]["priority"] == "medium" and alerts["items"][0]["tab"] == "checklist"
    notes = client.get("/api/notifications").json()["notifications"]
    assert any(n.get("source") == "brief" and n["title"] == "Collect contributions" for n in notes)
