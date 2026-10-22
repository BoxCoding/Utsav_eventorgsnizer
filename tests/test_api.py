from datetime import date, timedelta

from backend.app import ai
from backend.main import app
from fastapi.testclient import TestClient
from tests.conftest import event_payload


def _create(client, **kw) -> dict:
    r = client.post("/api/events", json=event_payload(**kw))
    assert r.status_code == 201, r.text
    return r.json()


def test_health_reports_offline_mode():
    body = TestClient(app).get("/api/health").json()
    assert body == {"status": "ok", "llm": "offline", "db": "ok"}


def test_security_headers_present():
    r = TestClient(app).get("/api/health")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_routes_require_sign_in():
    anon = TestClient(app)
    assert anon.get("/api/events").status_code == 401
    assert anon.get("/api/auth/session").json() == {"user": None}


def test_login_logout_and_rate_limit():
    c = TestClient(app)
    creds = {"name": "Meera", "email": "Meera@Example.com", "password": "correct-horse"}
    assert c.post("/api/auth/register", json=creds).status_code == 201
    assert c.post("/api/auth/register", json=creds).status_code == 409
    c.post("/api/auth/logout")
    assert c.get("/api/events").status_code == 401
    ok = c.post("/api/auth/login", json={"email": "meera@example.com", "password": "correct-horse"})
    assert ok.status_code == 200
    bad = {"email": "meera@example.com", "password": "wrong-password"}
    codes = [c.post("/api/auth/login", json=bad).status_code for _ in range(6)]
    assert codes[:4] == [401] * 4 and codes[-1] == 429


def test_create_returns_full_plan(client):
    body = _create(client)
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


def test_users_cannot_see_each_others_events(client):
    event_id = _create(client)["event"]["id"]
    other = TestClient(app)
    other.post(
        "/api/auth/register",
        json={"name": "Eve", "email": "eve@example.com", "password": "s3cret-pass"},
    )
    assert other.get(f"/api/events/{event_id}").status_code == 404
    assert other.patch(f"/api/events/{event_id}", json={"guests": 1}).status_code == 404
    assert other.delete(f"/api/events/{event_id}").status_code == 404
    assert other.get("/api/events").json()["events"] == []


def test_patch_checklist_spend_and_what_if(client):
    event_id = _create(client)["event"]["id"]
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


def test_ideas_fall_back_offline_and_are_cached(client):
    event_id = _create(client, kind="birthday", budget=60_000, guests=40)["event"]["id"]
    ideas = client.post(f"/api/events/{event_id}/ideas").json()["ideas"]
    assert ideas["source"] == "offline"
    assert ideas["decor"] and ideas["palette"]
    assert "marwari" in ideas["tagline"].lower()
    assert client.get(f"/api/events/{event_id}").json()["event"]["ideas"] == ideas


def test_ask_is_grounded_in_plan(client):
    event_id = _create(client)["event"]["id"]
    r = client.post(f"/api/events/{event_id}/ask", json={"question": "How is my budget?"})
    body = r.json()
    assert body["source"] == "offline"
    assert "₹15,00,000" in body["answer"]
    nxt = client.post(f"/api/events/{event_id}/ask", json={"question": "What next?"}).json()
    assert "Next up" in nxt["answer"]
    long = client.post(f"/api/events/{event_id}/ask", json={"question": "x" * 501})
    assert long.status_code == 422


def test_calendar_export(client):
    event_id = _create(client)["event"]["id"]
    r = client.get(f"/api/events/{event_id}/calendar.ics")
    assert r.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in r.text


def test_delete_event(client):
    event_id = _create(client)["event"]["id"]
    assert client.delete(f"/api/events/{event_id}").status_code == 204
    assert client.get(f"/api/events/{event_id}").status_code == 404


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
    event_id = _create(client)["event"]["id"]
    ideas = client.post(f"/api/events/{event_id}/ideas").json()["ideas"]
    assert ideas["source"] == "gemini" and ideas["theme"] == "Rajputana Rose"


def test_notifications_endpoint_aggregates_user_events(client):
    soon = (date.today() + timedelta(days=3)).isoformat()
    _create(client, kind="birthday", event_date=soon, budget=20_000, guests=50)
    notes = client.get("/api/notifications").json()["notifications"]
    assert notes and notes[0]["priority"] == "critical"
    fields = {"id", "event_id", "event_name", "priority", "title", "message", "tab"}
    assert fields <= notes[0].keys()
    assert TestClient(app).get("/api/notifications").status_code == 401


def test_invite_fallback_gives_three_concepts_from_given_facts(client):
    event_id = _create(client)["event"]["id"]
    r = client.post(
        f"/api/events/{event_id}/invite",
        json={"tone": "fun", "host": "Asha & Rohan", "venue": "Rambagh Palace", "time": "7 pm"},
    )
    invite = r.json()["invite"]
    assert invite["source"] == "offline" and len(invite["concepts"]) == 3
    assert {c["design"]["layout"] for c in invite["concepts"]} == {"framed", "centered", "poster"}
    first = invite["concepts"][0]
    assert "Rambagh Palace" in first["invite_body"] and "7 pm" in first["invite_body"]
    assert first["whatsapp"].startswith("Hi {name}")
    assert first["email_body"].startswith("Dear {name},")
    assert first["hashtag"].startswith("#") and " " not in first["hashtag"]
    assert client.get(f"/api/events/{event_id}").json()["event"]["invite"] == invite
    assert client.post(f"/api/events/{event_id}/invite", json={"tone": "rude"}).status_code == 422


def test_artwork_painted_stored_and_served(client, monkeypatch):
    from backend.app.routers import events as events_router

    prompts = []

    async def fake_image(prompt, aspect):
        prompts.append((prompt, aspect))
        return "image/png", b"\x89PNG fake"

    monkeypatch.setattr(events_router, "generate_image", fake_image)
    event_id = _create(client)["event"]["id"]
    assert client.post(
        f"/api/events/{event_id}/invite/art", json={"concept": 0, "format": "invite"}
    ).status_code == 404  # no concepts yet
    client.post(f"/api/events/{event_id}/invite", json={"tone": "elegant"})
    r = client.post(f"/api/events/{event_id}/invite/art", json={"concept": 1, "format": "banner"})
    assert r.json() == {"key": "1-banner"}
    assert prompts[0][1] == "21:9" and "no text" in prompts[0][0].lower()
    img = client.get(f"/api/events/{event_id}/invite/art/1-banner")
    assert img.headers["content-type"] == "image/png" and img.content == b"\x89PNG fake"
    assert client.get(f"/api/events/{event_id}/invite/art").json() == {"art": ["1-banner"]}
    # New concepts invalidate old artwork.
    client.post(f"/api/events/{event_id}/invite", json={"tone": "fun"})
    assert client.get(f"/api/events/{event_id}/invite/art/1-banner").status_code == 404


def test_artwork_offline_is_a_clear_503(client):
    event_id = _create(client)["event"]["id"]
    client.post(f"/api/events/{event_id}/invite", json={"tone": "elegant"})
    r = client.post(f"/api/events/{event_id}/invite/art", json={"concept": 0, "format": "invite"})
    assert r.status_code == 503


def test_guest_list_saved_and_validated(client):
    event_id = _create(client)["event"]["id"]
    guests = [
        {"name": "Meera", "email": "meera@example.com"},
        {"name": "Raj", "phone": "+91 98765 43210"},
    ]
    body = client.patch(f"/api/events/{event_id}", json={"guest_list": guests}).json()
    assert [g["name"] for g in body["event"]["guest_list"]] == ["Meera", "Raj"]
    bad_list = [{"name": "X", "email": "nope"}]
    bad = client.patch(f"/api/events/{event_id}", json={"guest_list": bad_list})
    assert bad.status_code == 422


def test_invite_output_is_validated():
    design = {"layout": "poster", "type": "playful", "text_tone": "dark",
              "palette": ["#112233", "red"], "art_prompt": "confetti"}
    good = {**{key: "x" for key in ai.COPY_LIMITS}, "hashtag": "#Big Day!", "design": design}
    [clean] = ai._clean_invite({"concepts": [good, {"name": "broken"}]})
    assert clean["hashtag"] == "#BigDay" and clean["design"]["palette"] == ["#112233"]
    weird = ai._clean_concept({**good, "design": {**design, "layout": "<script>"}})
    assert weird["design"]["layout"] == "framed"
    for bad in (None, {"concepts": []}, {"concepts": [{"name": "x"}]}):
        try:
            ai._clean_invite(bad)
        except ai.LLMUnavailableError:
            continue
        raise AssertionError(f"accepted {bad!r}")
    prompt = ai.art_prompt(clean, "invite")
    assert "upper half" in prompt and "no text" in prompt.lower()


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
    body = _create(client, currency="EUR", budget=40_000, brief="Garden wedding, vegan menu",
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
    body = _create(client, kind="birthday", budget=60_000, guests=40, custom_tasks=[
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
    event_id = _create(client, kind="birthday", budget=60_000, guests=40)["event"]["id"]
    r = client.post(f"/api/events/{event_id}/replan", json={"brief": "Now 80 guests, same party"})
    assert r.json()["fields"]["kind"] == "birthday" and r.json()["fields"]["guests"] == 80
    assert "RE-PLAN" in seen["system"] and '"guests": 40' in seen["system"]
    other = TestClient(app)
    other.post("/api/auth/register",
               json={"name": "Z", "email": "z@example.com", "password": "s3cret-pass"})
    assert other.post(f"/api/events/{event_id}/replan",
                      json={"brief": "Now 80 guests, same party"}).status_code == 404


def test_static_files_revalidate_and_brief_has_suggestions(client):
    assert TestClient(app).get("/js/home.js").headers["cache-control"] == "no-cache"
    body = client.post("/api/events/brief", json={"brief": "Community diya festival, 300 people"})
    assert body.json()["suggestions"]


def test_assets_are_served_under_versioned_urls():
    anon = TestClient(app)
    page = anon.get("/")
    assert page.headers["cache-control"] == "no-cache"
    prefix = page.text.split('src="')[1].split("js/main.js")[0]
    assert prefix.startswith("/v/") and f'href="{prefix}styles.css"' in page.text
    asset = anon.get(f"{prefix}js/home.js")  # relative imports inherit the version
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    assert anon.get(f"{prefix}%2e%2e/backend/main.py").status_code == 404
    assert anon.get(f"{prefix}nope.js").status_code == 404


def test_event_specific_categories_skips_and_spend_pruning(client):
    cats = {"Food & prasad": 0.5, "Puja samagri": 0.2, "Mehndi artists": 0.15,
            "Decor & lighting": 0.1, "Contingency": 0.05}
    body = _create(client, kind="community", budget=240_000, guests=400, split_override=cats,
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
    body = _create(client, kind="community", split_override=cats,
                   custom_tasks=out["custom_tasks"], skipped=out["skipped"])
    plan = body["plan"]
    assert plan["ai_checklist"] and len(plan["tasks"]) == 10
    assert {t["category"] for t in plan["tasks"]} == {"Planning", "Food & prasad"}
    assert [ln["category"] for ln in plan["budget"]["lines"]] == list(cats)  # no Planning line


def test_run_sheet_offline_saved_and_owned(client):
    event_id = _create(client)["event"]["id"]
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
    event_id = _create(client, kind="community", brief=brief)["event"]["id"]
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


def test_brief_details_never_put_a_date_in_the_time_box():
    merged = ai._merge_details({"tone": "fun", "host": "", "venue": "", "time": "", "rsvp": ""},
                               {"details": {"time": "Thursday, 29 October 2026", "venue": "Lawn"}})
    assert merged["time"] == "" and merged["venue"] == "Lawn"
    ok = ai._merge_details({"time": ""}, {"details": {"time": "6:30 pm onwards"}})
    assert ok["time"] == "6:30 pm onwards"


def test_ask_uses_brief_run_sheet_and_invite_details(client, monkeypatch):
    seen = {}

    async def fake_text(prompt, system=None, history=None, temperature=None):
        seen["prompt"], seen["system"] = prompt, system
        return "The puja is in the clubhouse."

    monkeypatch.setattr(ai.gemini_client, "generate_text", fake_text)
    brief = "Karwa Chauth: puja in the clubhouse, argh on the Tower 6 terrace"
    event_id = _create(client, kind="community", brief=brief)["event"]["id"]
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
    event_id = _create(client, kind="community", event_date=soon,
                       brief="Festival for residents, collect money from each flat")["event"]["id"]
    alerts = client.post(f"/api/events/{event_id}/alerts").json()["brief_alerts"]
    assert alerts["items"][0]["priority"] == "medium" and alerts["items"][0]["tab"] == "checklist"
    notes = client.get("/api/notifications").json()["notifications"]
    assert any(n.get("source") == "brief" and n["title"] == "Collect contributions" for n in notes)


def test_pwa_files_are_served():
    anon = TestClient(app)
    manifest = anon.get("/manifest.json").json()
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/"
    assert {i["sizes"] for i in manifest["icons"]} == {"192x192", "512x512"}
    for icon in manifest["icons"]:
        assert anon.get(icon["src"]).headers["content-type"] == "image/png"
    sw = anon.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
    page = anon.get("/").text
    assert 'rel="manifest"' in page and "apple-touch-icon" in page


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


def test_large_artwork_round_trips(client, monkeypatch):
    """Paintings can exceed Firestore's 1 MiB doc limit; the store chunks them."""
    from backend.app.routers import events as events_router
    big = bytes(range(256)) * 9000  # ~2.3 MB

    async def fake_image(prompt, aspect):
        return "image/jpeg", big

    monkeypatch.setattr(events_router, "generate_image", fake_image)
    event_id = _create(client)["event"]["id"]
    client.post(f"/api/events/{event_id}/invite", json={"tone": "elegant"})
    client.post(f"/api/events/{event_id}/invite/art", json={"concept": 0, "format": "invite"})
    assert client.get(f"/api/events/{event_id}/invite/art/0-invite").content == big
    assert client.delete(f"/api/events/{event_id}").status_code == 204
