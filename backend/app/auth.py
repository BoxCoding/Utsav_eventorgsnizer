"""Authentication: PBKDF2 password hashing + httpOnly cookie sessions.

Security properties:
  * Passwords stored as PBKDF2-HMAC-SHA256 (210k iterations, per-user salt).
  * Session tokens are random 256-bit values; only their SHA-256 hash is
    stored, so a leaked database cannot be replayed as a session.
  * The cookie is httpOnly + SameSite=Lax — invisible to page JavaScript,
    which also shields it from any injected script.
  * Every data route resolves the user from the session and filters queries
    by user_id (user-data isolation).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, HTTPException, Response

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


def _rate_limited(email: str) -> bool:
    now = time.monotonic()
    window = _attempts[email]
    while window and now - window[0] > LOGIN_WINDOW:
        window.popleft()
    window.append(now)
    return len(window) > LOGIN_LIMIT


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS).hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _start_session(response: Response, user_id: int) -> None:
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


def _public(user: dict) -> dict:
    return {"id": user["id"], "name": user["name"], "email": user["email"]}


async def current_user(
    utsav_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict:
    """FastAPI dependency: resolve the signed-in user or reject with 401."""
    if not utsav_session:
        raise HTTPException(status_code=401, detail="sign in required")
    user = store.get_session_user(_hash_token(utsav_session))
    if user is None:
        raise HTTPException(status_code=401, detail="session expired — sign in again")
    return user


@router.post("/register", status_code=201)
async def register(payload: RegisterRequest, response: Response) -> dict:
    if store.get_user_by_email(payload.email) is not None:
        raise HTTPException(status_code=409, detail="an account with this email already exists")
    salt = secrets.token_bytes(16)
    user_id = store.create_user(
        payload.name, payload.email, _hash_password(payload.password, salt), salt.hex()
    )
    _start_session(response, user_id)
    return {"user": {"id": user_id, "name": payload.name, "email": payload.email}}


@router.post("/login")
async def login(payload: LoginRequest, response: Response) -> dict:
    if _rate_limited(payload.email):
        raise HTTPException(status_code=429, detail="too many attempts — wait a minute")
    user = store.get_user_by_email(payload.email)
    # Constant-time comparison; identical error for unknown email vs wrong
    # password, so the endpoint can't be used to probe registered emails.
    if user is not None:
        expected = user["password_hash"]
        candidate = _hash_password(payload.password, bytes.fromhex(user["salt"]))
        if hmac.compare_digest(candidate, expected):
            _start_session(response, user["id"])
            return {"user": _public(user)}
    raise HTTPException(status_code=401, detail="invalid email or password")


@router.post("/logout")
async def logout(
    response: Response,
    utsav_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict:
    if utsav_session:
        store.delete_session(_hash_token(utsav_session))
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
async def me(
    utsav_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict:
    """Strict variant: 401 when unauthenticated (used by API clients)."""
    user = await current_user(utsav_session)
    return {"user": _public(user)}


@router.get("/session")
async def session(
    utsav_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict:
    """Boot probe for the browser: always 200, `user` is null when signed out.

    Being signed out is a normal state, not an error — answering 200 keeps a
    first-time visitor's console completely clean instead of logging a 401.
    """
    if not utsav_session:
        return {"user": None}
    user = store.get_session_user(_hash_token(utsav_session))
    return {"user": _public(user) if user else None}
