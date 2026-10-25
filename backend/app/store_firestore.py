"""Firestore persistence for production (UTSAV_STORE=firestore).

Same functions and return shapes as the SQLite store, so routes and auth are unchanged:
  * numeric ids come from transactional counters (counters/ids), keeping URLs stable;
  * email uniqueness is enforced by a reserved doc per email (emails/{email});
  * every event read/write checks user_id (data isolation, as in SQLite);
  * AI artwork is split into <=900 KB chunks to stay under Firestore's 1 MiB doc limit.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore

_db: firestore.Client | None = None
CHUNK = 900_000

EVENT_DEFAULTS: dict[str, Any] = {
    "city": "", "vibe": "", "tradition": "", "currency": "INR", "brief": "", "budget_note": "",
    "done": [], "spend": {}, "ideas": None, "invite": None, "guest_list": [],
    "custom_tasks": [], "split_override": None, "skipped": [], "run_sheet": None,
    "brief_alerts": None,
}
EDITABLE = {
    "name", "kind", "event_date", "guests", "budget", "city", "vibe", "tradition", "currency",
    "brief", "budget_note",
} | {k for k in EVENT_DEFAULTS if k not in {"city", "vibe", "tradition", "currency", "brief",
                                             "budget_note"}}


def db() -> firestore.Client:
    """The Firestore client, created on first use."""
    global _db
    if _db is None:  # lazy: importing the module must not need credentials
        _db = firestore.Client()
    return _db


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _next_id(kind: str) -> int:
    ref = db().collection("counters").document("ids")

    @firestore.transactional
    def bump(tx: firestore.Transaction) -> int:
        """Read, increment and store the counter inside the transaction."""
        snap = ref.get(transaction=tx)
        value = int((snap.to_dict() or {}).get(kind, 0)) + 1
        tx.set(ref, {kind: value}, merge=True)
        return value

    return bump(db().transaction())


def _data(snap: Any) -> dict[str, Any]:
    """A snapshot's fields ({} for a missing document)."""
    return snap.to_dict() or {}


def init_db() -> None:
    """Nothing to create: Firestore collections appear on first write."""


# ── users & sessions ────────────────────────────────────────────────────
def create_user(name: str, email: str, password_hash: str, salt: str) -> int:
    """Insert a user and return the new id (raises ValueError if the email is taken)."""
    user_id = _next_id("users")
    try:  # create() fails if the email is taken: a race-free uniqueness check
        db().collection("emails").document(email).create({"user_id": user_id})
    except AlreadyExists as exc:
        raise ValueError("email already registered") from exc
    db().collection("users").document(str(user_id)).set({
        "id": user_id, "name": name, "email": email, "password_hash": password_hash,
        "salt": salt, "created_at": _now(),
    })
    return user_id


def get_user_by_email(email: str) -> dict | None:
    """The user row for an email, or None."""
    link = db().collection("emails").document(email).get()
    if not link.exists:
        return None
    user = db().collection("users").document(str(_data(link)["user_id"])).get()
    return user.to_dict() if user.exists else None


def create_session(token_hash: str, user_id: int, expires_at: str) -> None:
    """Store a session by the hash of its token."""
    db().collection("sessions").document(token_hash).set(
        {"user_id": user_id, "expires_at": expires_at})


def get_session_user(token_hash: str) -> dict | None:
    """The signed-in user for an unexpired session token hash, or None."""
    session = db().collection("sessions").document(token_hash).get()
    if not session.exists or _data(session)["expires_at"] <= _now():
        return None
    user = db().collection("users").document(str(_data(session)["user_id"])).get()
    if not user.exists:
        return None
    u = _data(user)
    return {"id": u["id"], "name": u["name"], "email": u["email"]}


def delete_session(token_hash: str) -> None:
    """Remove a session (sign-out)."""
    db().collection("sessions").document(token_hash).delete()


# ── events ──────────────────────────────────────────────────────────────
# Firestore returns map keys alphabetically; the budget split's order is meaningful
# (AI-designed categories, Contingency last), so it is stored as ordered pairs.
def _to_doc(fields: dict[str, Any]) -> dict[str, Any]:
    split = fields.get("split_override")
    if isinstance(split, dict):
        fields = {**fields, "split_override": [{"k": k, "v": v} for k, v in split.items()]}
    return fields


def _event(snap: Any) -> dict[str, Any]:
    event = {**EVENT_DEFAULTS, **_data(snap)}
    if isinstance(event["split_override"], list):
        event["split_override"] = {p["k"]: p["v"] for p in event["split_override"]}
    return event


def create_event(user_id: int, fields: dict[str, Any]) -> int:
    """Insert an event for a user and return its id."""
    event_id = _next_id("events")
    doc = {**EVENT_DEFAULTS, **{k: v for k, v in fields.items() if k in EDITABLE and v is not None}}
    db().collection("events").document(str(event_id)).set(
        {**_to_doc(doc), "id": event_id, "user_id": user_id, "created_at": _now()})
    return event_id


def list_events(user_id: int) -> list[dict[str, Any]]:
    # Sorted here rather than in the query: avoids needing a composite index.
    """All of a user's events, soonest first."""
    snaps = db().collection("events").where(filter=firestore.FieldFilter("user_id", "==", user_id))
    return sorted((_event(s) for s in snaps.stream()), key=lambda e: e["event_date"])


def get_event(user_id: int, event_id: int) -> dict[str, Any] | None:
    """One event if it belongs to the user, else None."""
    snap = db().collection("events").document(str(event_id)).get()
    if not snap.exists or _data(snap).get("user_id") != user_id:
        return None
    return _event(snap)


def update_event(user_id: int, event_id: int, fields: dict[str, Any]) -> None:
    """Update whitelisted fields of the user's event."""
    changes = {k: v for k, v in fields.items() if k in EDITABLE}
    if changes and get_event(user_id, event_id) is not None:
        db().collection("events").document(str(event_id)).update(_to_doc(changes))


def delete_event(user_id: int, event_id: int) -> bool:
    """Delete the user's event; returns False if it wasn't theirs."""
    if get_event(user_id, event_id) is None:
        return False
    clear_art(event_id)
    db().collection("events").document(str(event_id)).delete()
    return True


# ── WhatsApp message ids -> event ───────────────────────────────────────
def record_wa(user_id: int, event_id: int, message_ids: list[str]) -> None:
    """Remember which event and user sent each WhatsApp message id."""
    batch = db().batch()
    for m in message_ids:
        batch.set(db().collection("wa_messages").document(m),
                  {"user_id": user_id, "event_id": event_id})
    batch.commit()


def wa_owner(message_id: str) -> tuple[int, int] | None:
    """(user id, event id) for a WhatsApp message id, or None."""
    snap = db().collection("wa_messages").document(message_id).get()
    return (_data(snap)["user_id"], _data(snap)["event_id"]) if snap.exists else None


# ── AI artwork, chunked ─────────────────────────────────────────────────
def _art(event_id: int) -> Any:
    return db().collection("events").document(str(event_id)).collection("art")


def save_art(event_id: int, key: str, mime: str, data: bytes) -> None:
    """Store (or replace) one artwork image for an event."""
    parts = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]
    batch = db().batch()
    for i, part in enumerate(parts):
        batch.set(_art(event_id).document(f"{key}.{i}"), {"data": part})
    batch.set(_art(event_id).document(key), {"key": key, "mime": mime, "parts": len(parts)})
    batch.commit()


def get_art(event_id: int, key: str) -> tuple[str, bytes] | None:
    """One stored artwork as (mime type, bytes), or None."""
    meta = _art(event_id).document(key).get()
    if not meta.exists:
        return None
    m = _data(meta)
    data = b"".join(_data(_art(event_id).document(f"{key}.{i}").get())["data"]
                    for i in range(m["parts"]))
    return m["mime"], data


def art_keys(event_id: int) -> list[str]:
    """Keys of all artwork stored for an event."""
    return [_data(d)["key"] for d in _art(event_id).stream() if "key" in _data(d)]


def clear_art(event_id: int) -> None:
    """Delete all artwork for an event."""
    for doc in _art(event_id).stream():
        doc.reference.delete()
