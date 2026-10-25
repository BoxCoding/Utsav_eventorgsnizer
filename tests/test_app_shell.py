"""Serving the web app: versioned assets, PWA files, caching."""

from backend.main import app
from fastapi.testclient import TestClient


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
