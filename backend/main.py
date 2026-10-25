"""Utsav, a GenAI event planning assistant. Run: `uvicorn backend.main:app --port 8101`."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .app import auth, store
from .app.config import ROOT, settings
from .app.routers import events, whatsapp

logging.basicConfig(level=logging.INFO)

CSP = (
    "default-src 'self'; img-src 'self' data:; script-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


store.init_db()  # at import, not lifespan: serverless runtimes may skip lifespan events
app = FastAPI(title="Utsav", version="1.0.0")
app.add_middleware(GZipMiddleware, minimum_size=800)
# Only the native app shells; the web app is same-origin. No cookies cross origins.
app.add_middleware(
    CORSMiddleware, allow_origins=list(settings.app_origins), allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Utsav-Client"], max_age=86400,
)


UNSAFE = {"POST", "PATCH", "PUT", "DELETE"}


def _cross_site(request: Request) -> bool:
    """True for a cookie-authenticated write from another site (CSRF).

    SameSite=Lax already blocks most; this also covers same-site subdomains and older
    browsers.
    """
    origin = request.headers.get("origin")
    return (request.method in UNSAFE and auth.COOKIE_NAME in request.cookies
            and bool(origin) and urlsplit(origin).netloc != request.headers.get("host"))


@app.middleware("http")
async def security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Block cross-site cookie writes and add security headers to every response."""
    response: Response
    if _cross_site(request):
        response = JSONResponse({"detail": "cross-site request blocked"}, status_code=403)
    else:
        response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    # Browsers ignore HSTS on plain-http localhost, so it's safe to always send.
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    else:
        # Revalidate app files on every load (cheap via ETag) so a deploy never leaves a
        # browser running stale JS/CSS against a newer page.
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


@app.get("/api/health")
async def health() -> dict:
    """Liveness plus which AI engine and database are in use."""
    try:
        store.list_events(0)
        db = "ok"
    except Exception as exc:  # report instead of crashing so bad deploys are diagnosable
        db = f"error: {type(exc).__name__}"
    return {"status": "ok", "llm": "gemini" if settings.llm_enabled else "offline", "db": db}


FRONTEND = (ROOT / "frontend").resolve()


def build_id() -> str:
    """An id that changes whenever any frontend file changes.

    Versioned asset URLs then miss every browser cache, so nobody runs stale JS/CSS
    against a newer page.
    """
    latest = max(p.stat().st_mtime_ns for p in FRONTEND.rglob("*") if p.is_file())
    return format(latest, "x")[-10:]


@app.get("/", include_in_schema=False)
async def index() -> HTMLResponse:
    """The app page, with asset URLs pinned to the current build."""
    prefix = f"/v/{build_id()}/"
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="styles.css"', f'href="{prefix}styles.css"')
    html = html.replace('src="js/main.js"', f'src="{prefix}js/main.js"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/v/{build}/{path:path}", include_in_schema=False)
async def versioned_asset(build: str, path: str) -> FileResponse:
    """Serve a frontend file under a build-specific URL; safe to cache for a year.

    Relative module imports inherit the prefix, so every JS module is versioned too.
    """
    file = (FRONTEND / path).resolve()
    if FRONTEND not in file.parents or not file.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(file, headers={"Cache-Control": "public, max-age=31536000, immutable"})


app.include_router(auth.router)
app.include_router(events.router)
app.include_router(events.notifications_router)
app.include_router(whatsapp.router)
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
