"""Invitation concepts, AI artwork and proof-read posters."""

from backend.app import ai
from tests.conftest import create_event


def test_invite_fallback_gives_three_concepts_from_given_facts(client):
    event_id = create_event(client)["event"]["id"]
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
    event_id = create_event(client)["event"]["id"]
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


def test_poster_is_proofread_and_retried(client, monkeypatch):
    from backend.app import ai
    from backend.app.routers import events as events_router

    prompts, verdicts = [], [["VENUE: Rambagh Palace"], []]  # first attempt misspells the venue

    async def fake_image(prompt, aspect):
        prompts.append((prompt, aspect))
        return "image/png", b"poster"

    async def fake_proof(image, mime, lines):
        assert ("VENUE", "Rambagh Palace") in lines["info"] and lines["info"][0][0] == "DATE"
        return verdicts.pop(0)

    monkeypatch.setattr(events_router, "generate_image", fake_image)
    monkeypatch.setattr(ai, "proofread_poster", fake_proof)
    event_id = create_event(client)["event"]["id"]
    client.post(f"/api/events/{event_id}/invite",
                json={"tone": "elegant", "venue": "Rambagh Palace", "time": "7 pm"})
    r = client.post(f"/api/events/{event_id}/invite/art", json={"concept": 0, "format": "poster"})
    assert r.json() == {"key": "0-poster", "verified": True}
    assert len(prompts) == 2 and prompts[0][1] == "2:3"
    assert "'VENUE: Rambagh Palace'" in prompts[0][0] and "'TIME: 7 pm'" in prompts[0][0]
    assert client.get(f"/api/events/{event_id}/invite/art/0-poster").content == b"poster"


def test_poster_that_never_passes_is_not_saved(client, monkeypatch):
    from backend.app import ai
    from backend.app.routers import events as events_router

    async def fake_image(prompt, aspect):
        return "image/png", b"bad"

    async def always_wrong(image, mime, lines):
        return [lines["title"]]

    monkeypatch.setattr(events_router, "generate_image", fake_image)
    monkeypatch.setattr(ai, "proofread_poster", always_wrong)
    event_id = create_event(client)["event"]["id"]
    client.post(f"/api/events/{event_id}/invite", json={"tone": "fun"})
    r = client.post(f"/api/events/{event_id}/invite/art", json={"concept": 2, "format": "poster"})
    assert r.status_code == 422
    assert client.get(f"/api/events/{event_id}/invite/art").json() == {"art": []}


def test_artwork_offline_is_a_clear_503(client):
    event_id = create_event(client)["event"]["id"]
    client.post(f"/api/events/{event_id}/invite", json={"tone": "elegant"})
    r = client.post(f"/api/events/{event_id}/invite/art", json={"concept": 0, "format": "invite"})
    assert r.status_code == 503


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


def test_large_artwork_round_trips(client, monkeypatch):
    """Paintings can exceed Firestore's 1 MiB doc limit; the store chunks them."""
    from backend.app.routers import events as events_router
    big = bytes(range(256)) * 9000  # ~2.3 MB

    async def fake_image(prompt, aspect):
        return "image/jpeg", big

    monkeypatch.setattr(events_router, "generate_image", fake_image)
    event_id = create_event(client)["event"]["id"]
    client.post(f"/api/events/{event_id}/invite", json={"tone": "elegant"})
    client.post(f"/api/events/{event_id}/invite/art", json={"concept": 0, "format": "invite"})
    assert client.get(f"/api/events/{event_id}/invite/art/0-invite").content == big
    assert client.delete(f"/api/events/{event_id}").status_code == 204


def test_poster_retries_when_proofreading_is_unavailable(client, monkeypatch):
    from backend.app import ai
    from backend.app.gemini_client import LLMUnavailableError
    from backend.app.routers import events as events_router

    calls = []

    async def fake_image(prompt, aspect):
        calls.append(1)
        return "image/png", b"poster"

    async def flaky_proof(image, mime, lines):
        if len(calls) == 1:
            raise LLMUnavailableError("malformed JSON")
        return []

    monkeypatch.setattr(events_router, "generate_image", fake_image)
    monkeypatch.setattr(ai, "proofread_poster", flaky_proof)
    event_id = create_event(client)["event"]["id"]
    client.post(f"/api/events/{event_id}/invite", json={"tone": "fun"})
    r = client.post(f"/api/events/{event_id}/invite/art", json={"concept": 0, "format": "poster"})
    assert r.status_code == 200 and len(calls) == 2
