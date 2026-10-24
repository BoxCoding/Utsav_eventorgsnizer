"""Authentication: PBKDF2 password hashing + httpOnly cookie sessions.

Security properties:
  * Passwords stored as PBKDF2-HMAC-SHA256 (210k iterations, per-user salt).
  * Session tokens are random 256-bit values; only their SHA-256 hash is
    stored, so a leaked database cannot be replayed as a session.
  * The cookie is httpOnly + SameSite=Lax — invisible to page JavaScript,
    which also shields it from any injected script.
  * Every data route resolves the user from the session and filters queries
    by user_id (user-data isolation).
  * The native app (bundled web assets, a different origin) can't use the cookie, so it
    asks for the token once at sign-in (X-Utsav-Client: native) and sends it as a bearer
    header. Bearer headers are never attached automatically, so this adds no CSRF risk.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Header, HTTPException, Response

from . import store
from .config import settings
from .schemas import LoginRequest, RegisterRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "utsav_session"
PBKDF2_ITERATIONS = 210_000
SESSION_TTL = timedelta(days=7)
LOGIN_LIMIT, LOGIN_WINDOW = 5, 60.0  # attempts per email per minute
# shortcut: per-process memory, resets on restart; move to Redis if running >1 instance.
_attempts: dict[str, deque[float]] = defaultdict(deque)


def prune_window(hits: deque[float], window: float, now: float) -> None:
    """Drop timestamps older than `window` seconds (shared by the login and AI limiters)."""
    while hits and now - hits[0] > window:
        hits.popleft()


def _rate_limited(email: str) -> bool:
    now = time.monotonic()
    window = _attempts[email]
    prune_window(window, LOGIN_WINDOW, now)
    window.append(now)
    return len(window) > LOGIN_LIMIT


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS).hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _start_session(response: Response, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + SESSION_TTL
    store.create_session(_hash_token(token), user_id, expires_at.strftime("%Y-%m-%d %H:%M:%S"))
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return token


def _token(cookie: str | None, authorization: str | None) -> str | None:
    if cookie:
        return cookie
    scheme, _, value = (authorization or "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None


def _signed_in(user: dict, token: str, client: str | None) -> dict:
    """Only the native app is handed its token; the web keeps it in the httpOnly cookie."""
    return {"user": _public(user), **({"token": token} if client == "native" else {})}


def _public(user: dict) -> dict:
    return {"id": user["id"], "name": user["name"], "email": user["email"]}


async def current_user(
    utsav_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    authorization: str | None = Header(default=None),
) -> dict:
    """FastAPI dependency: resolve the signed-in user or reject with 401."""
    token = _token(utsav_session, authorization)
    if not token:
        raise HTTPException(status_code=401, detail="sign in required")
    user = store.get_session_user(_hash_token(token))
    if user is None:
        raise HTTPException(status_code=401, detail="session expired — sign in again")
    return user


@router.post("/register", status_code=201)
async def register(
    payload: RegisterRequest, response: Response,
    x_utsav_client: str | None = Header(default=None),
) -> dict:
    if store.get_user_by_email(payload.email) is not None:
        raise HTTPException(status_code=409, detail="an account with this email already exists")
    salt = secrets.token_bytes(16)
    user_id = store.create_user(
        payload.name, payload.email, _hash_password(payload.password, salt), salt.hex()
    )
    token = _start_session(response, user_id)
    user = {"id": user_id, "name": payload.name, "email": payload.email}
    return _signed_in(user, token, x_utsav_client)


@router.post("/login")
async def login(
    payload: LoginRequest, response: Response,
    x_utsav_client: str | None = Header(default=None),
) -> dict:
    if _rate_limited(payload.email):
        raise HTTPException(status_code=429, detail="too many attempts — wait a minute")
    user = store.get_user_by_email(payload.email)
    # Constant-time comparison; identical error for unknown email vs wrong
    # password, so the endpoint can't be used to probe registered emails.
    if user is not None:
        expected = user["password_hash"]
        candidate = _hash_password(payload.password, bytes.fromhex(user["salt"]))
        if hmac.compare_digest(candidate, expected):
            token = _start_session(response, user["id"])
            return _signed_in(user, token, x_utsav_client)
    raise HTTPException(status_code=401, detail="invalid email or password")


@router.post("/logout")
async def logout(
    response: Response,
    utsav_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    authorization: str | None = Header(default=None),
) -> dict:
    token = _token(utsav_session, authorization)
    if token:
        store.delete_session(_hash_token(token))
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
async def me(
    utsav_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    authorization: str | None = Header(default=None),
) -> dict:
    """Strict variant: 401 when unauthenticated (used by API clients)."""
    user = await current_user(utsav_session, authorization)
    return {"user": _public(user)}


@router.get("/session")
async def session(
    utsav_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    authorization: str | None = Header(default=None),
) -> dict:
    """Boot probe for the browser: always 200, `user` is null when signed out.

    Being signed out is a normal state, not an error — answering 200 keeps a
    first-time visitor's console completely clean instead of logging a 401.
    """
    token = _token(utsav_session, authorization)
    if not token:
        return {"user": None}
    user = store.get_session_user(_hash_token(token))
    return {"user": _public(user) if user else None}
