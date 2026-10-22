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
        snap = ref.get(transaction=tx)
        value = int((snap.to_dict() or {}).get(kind, 0)) + 1
        tx.set(ref, {kind: value}, merge=True)
        return value

    return bump(db().transaction())


def init_db() -> None:
    """Nothing to create: Firestore collections appear on first write."""


# ── users & sessions ────────────────────────────────────────────────────
def create_user(name: str, email: str, password_hash: str, salt: str) -> int:
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
    link = db().collection("emails").document(email).get()
    if not link.exists:
        return None
    user = db().collection("users").document(str(link.to_dict()["user_id"])).get()
    return user.to_dict() if user.exists else None


def create_session(token_hash: str, user_id: int, expires_at: str) -> None:
    db().collection("sessions").document(token_hash).set(
        {"user_id": user_id, "expires_at": expires_at})


def get_session_user(token_hash: str) -> dict | None:
    session = db().collection("sessions").document(token_hash).get()
    if not session.exists or session.to_dict()["expires_at"] <= _now():
        return None
    user = db().collection("users").document(str(session.to_dict()["user_id"])).get()
    if not user.exists:
        return None
    u = user.to_dict()
    return {"id": u["id"], "name": u["name"], "email": u["email"]}


def delete_session(token_hash: str) -> None:
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
    event = {**EVENT_DEFAULTS, **snap.to_dict()}
    if isinstance(event["split_override"], list):
        event["split_override"] = {p["k"]: p["v"] for p in event["split_override"]}
    return event


def create_event(user_id: int, fields: dict[str, Any]) -> int:
    event_id = _next_id("events")
    doc = {**EVENT_DEFAULTS, **{k: v for k, v in fields.items() if k in EDITABLE and v is not None}}
    db().collection("events").document(str(event_id)).set(
        {**_to_doc(doc), "id": event_id, "user_id": user_id, "created_at": _now()})
    return event_id


def list_events(user_id: int) -> list[dict[str, Any]]:
    # Sorted here rather than in the query: avoids needing a composite index.
    snaps = db().collection("events").where(filter=firestore.FieldFilter("user_id", "==", user_id))
    return sorted((_event(s) for s in snaps.stream()), key=lambda e: e["event_date"])


def get_event(user_id: int, event_id: int) -> dict[str, Any] | None:
    snap = db().collection("events").document(str(event_id)).get()
    if not snap.exists or snap.to_dict().get("user_id") != user_id:
        return None
    return _event(snap)


def update_event(user_id: int, event_id: int, fields: dict[str, Any]) -> None:
    changes = {k: v for k, v in fields.items() if k in EDITABLE}
    if changes and get_event(user_id, event_id) is not None:
        db().collection("events").document(str(event_id)).update(_to_doc(changes))


def delete_event(user_id: int, event_id: int) -> bool:
    if get_event(user_id, event_id) is None:
        return False
    clear_art(event_id)
    db().collection("events").document(str(event_id)).delete()
    return True


# ── AI artwork, chunked ─────────────────────────────────────────────────
def _art(event_id: int) -> Any:
    return db().collection("events").document(str(event_id)).collection("art")


def save_art(event_id: int, key: str, mime: str, data: bytes) -> None:
    parts = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]
    batch = db().batch()
    for i, part in enumerate(parts):
        batch.set(_art(event_id).document(f"{key}.{i}"), {"data": part})
    batch.set(_art(event_id).document(key), {"key": key, "mime": mime, "parts": len(parts)})
    batch.commit()


def get_art(event_id: int, key: str) -> tuple[str, bytes] | None:
    meta = _art(event_id).document(key).get()
    if not meta.exists:
        return None
    m = meta.to_dict()
    data = b"".join(_art(event_id).document(f"{key}.{i}").get().to_dict()["data"]
                    for i in range(m["parts"]))
    return m["mime"], data


def art_keys(event_id: int) -> list[str]:
    return [d.to_dict()["key"] for d in _art(event_id).stream() if "key" in d.to_dict()]


def clear_art(event_id: int) -> None:
    for doc in _art(event_id).stream():
        doc.reference.delete()
