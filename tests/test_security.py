"""Authentication, data isolation and the security layer."""

from backend.main import app
from fastapi.testclient import TestClient
from tests.conftest import create_event, event_payload


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


def test_users_cannot_see_each_others_events(client):
    event_id = create_event(client)["event"]["id"]
    other = TestClient(app)
    other.post(
        "/api/auth/register",
        json={"name": "Eve", "email": "eve@example.com", "password": "s3cret-pass"},
    )
    assert other.get(f"/api/events/{event_id}").status_code == 404
    assert other.patch(f"/api/events/{event_id}", json={"guests": 1}).status_code == 404
    assert other.delete(f"/api/events/{event_id}").status_code == 404
    assert other.get("/api/events").json()["events"] == []


def test_native_app_signs_in_with_a_bearer_token():
    app_client = TestClient(app)
    web = app_client.post("/api/auth/register", json={
        "name": "Web", "email": "web-only@example.com", "password": "s3cret-pass"})
    assert "token" not in web.json()  # the web keeps its session in the httpOnly cookie
    native = TestClient(app)
    r = native.post("/api/auth/login", headers={"X-Utsav-Client": "native"},
                    json={"email": "web-only@example.com", "password": "s3cret-pass"})
    token = r.json()["token"]
    native.cookies.clear()  # the app's origin can't use the cookie
    bearer = {"Authorization": f"Bearer {token}"}
    assert native.get("/api/auth/me").status_code == 401
    assert native.get("/api/auth/me", headers=bearer).json()["user"]["name"] == "Web"
    assert native.post("/api/events", json=event_payload(), headers=bearer).status_code == 201
    assert native.get("/api/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401
    native.post("/api/auth/logout", headers=bearer)
    assert native.get("/api/auth/me", headers=bearer).status_code == 401


def test_cors_allows_only_the_app_shells():
    c = TestClient(app)
    preflight = {"Access-Control-Request-Method": "PATCH",
                 "Access-Control-Request-Headers": "authorization,content-type"}
    ok = c.options("/api/events/1", headers={"Origin": "https://localhost", **preflight})
    assert ok.headers["access-control-allow-origin"] == "https://localhost"
    bad = c.options("/api/events/1", headers={"Origin": "https://evil.example", **preflight})
    assert "access-control-allow-origin" not in bad.headers


def test_hardening_headers_present():
    h = TestClient(app).get("/api/health").headers
    assert h["x-frame-options"] == "DENY" and "max-age" in h["strict-transport-security"]
    assert "camera=()" in h["permissions-policy"]


def test_cross_site_cookie_writes_are_blocked(client):
    evil = client.post("/api/events", json=event_payload(), headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    same = client.post("/api/events", json=event_payload(), headers={"Origin": "http://testserver"})
    assert same.status_code == 201


def test_ai_routes_have_a_per_user_quota(client, monkeypatch):
    from backend.app import limits

    event_id = create_event(client)["event"]["id"]
    monkeypatch.setattr(limits, "_hits", limits.defaultdict(limits.deque))
    codes = [client.post(f"/api/events/{event_id}/ask", json={"question": "Hi?"}).status_code
             for _ in range(41)]
    assert codes[:40] == [200] * 40 and codes[40] == 429
