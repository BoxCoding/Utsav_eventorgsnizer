"""Persistence. SQLite here; UTSAV_STORE=firestore swaps in store_firestore (same API).
Every event query is scoped by user_id (data isolation)."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    event_date TEXT NOT NULL,
    guests INTEGER NOT NULL,
    budget INTEGER NOT NULL,
    city TEXT NOT NULL DEFAULT '',
    vibe TEXT NOT NULL DEFAULT '',
    tradition TEXT NOT NULL DEFAULT '',
    done_json TEXT NOT NULL DEFAULT '[]',
    spend_json TEXT NOT NULL DEFAULT '{}',
    ideas_json TEXT,
    invite_json TEXT,
    guests_json TEXT NOT NULL DEFAULT '[]',
    currency TEXT NOT NULL DEFAULT 'INR',
    brief TEXT NOT NULL DEFAULT '',
    custom_json TEXT NOT NULL DEFAULT '[]',
    split_json TEXT,
    skip_json TEXT NOT NULL DEFAULT '[]',
    budget_note TEXT NOT NULL DEFAULT '',
    run_json TEXT,
    alerts_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);
CREATE TABLE IF NOT EXISTS artwork (
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    mime TEXT NOT NULL,
    data BLOB NOT NULL,
    PRIMARY KEY (event_id, key)
);
"""

EDITABLE = {
    "name", "kind", "event_date", "guests", "budget", "city", "vibe", "tradition", "currency",
    "brief", "budget_note",
}
JSON_COLUMNS = {
    "done": "done_json",
    "spend": "spend_json",
    "ideas": "ideas_json",
    "invite": "invite_json",
    "guest_list": "guests_json",
    "custom_tasks": "custom_json",
    "split_override": "split_json",
    "skipped": "skip_json",
    "run_sheet": "run_json",
    "brief_alerts": "alerts_json",
}
# Columns added after the first release; applied to older databases at startup.
MIGRATIONS = (
    "ALTER TABLE events ADD COLUMN invite_json TEXT",
    "ALTER TABLE events ADD COLUMN guests_json TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE events ADD COLUMN currency TEXT NOT NULL DEFAULT 'INR'",
    "ALTER TABLE events ADD COLUMN brief TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE events ADD COLUMN custom_json TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE events ADD COLUMN split_json TEXT",
    "ALTER TABLE events ADD COLUMN skip_json TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE events ADD COLUMN run_json TEXT",
    "ALTER TABLE events ADD COLUMN alerts_json TEXT",
    "ALTER TABLE events ADD COLUMN budget_note TEXT NOT NULL DEFAULT ''",
)


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(SCHEMA)
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
        for statement in MIGRATIONS:
            if statement.split()[5] not in existing:  # the column name
                conn.execute(statement)


# ── users & sessions ────────────────────────────────────────────────────
def create_user(name: str, email: str, password_hash: str, salt: str) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, salt) VALUES (?, ?, ?, ?)",
            (name, email, password_hash, salt),
        )
        return int(cur.lastrowid)


def get_user_by_email(email: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def create_session(token_hash: str, user_id: int, expires_at: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, user_id, expires_at),
        )


def get_session_user(token_hash: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT u.id, u.name, u.email FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.expires_at > datetime('now')",
            (token_hash,),
        ).fetchone()
    return dict(row) if row else None


def delete_session(token_hash: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


# ── events ──────────────────────────────────────────────────────────────
def _decode(row: sqlite3.Row) -> dict[str, Any]:
    event = dict(row)
    event["done"] = json.loads(event.pop("done_json"))
    event["spend"] = json.loads(event.pop("spend_json"))
    ideas = event.pop("ideas_json")
    event["ideas"] = json.loads(ideas) if ideas else None
    invite = event.pop("invite_json")
    event["invite"] = json.loads(invite) if invite else None
    event["guest_list"] = json.loads(event.pop("guests_json"))
    event["custom_tasks"] = json.loads(event.pop("custom_json"))
    split = event.pop("split_json")
    event["split_override"] = json.loads(split) if split else None
    event["skipped"] = json.loads(event.pop("skip_json"))
    run = event.pop("run_json")
    event["run_sheet"] = json.loads(run) if run else None
    alerts = event.pop("alerts_json")
    event["brief_alerts"] = json.loads(alerts) if alerts else None
    return event


def create_event(user_id: int, fields: dict[str, Any]) -> int:
    values: dict[str, Any] = {c: fields[c] for c in fields.keys() & EDITABLE}
    for key, column in JSON_COLUMNS.items():
        if fields.get(key) is not None:
            values[column] = json.dumps(fields[key])
    cols = sorted(values)
    with _conn() as conn:
        cur = conn.execute(
            f"INSERT INTO events (user_id, {', '.join(cols)}) "
            f"VALUES (?, {', '.join('?' for _ in cols)})",
            (user_id, *(values[c] for c in cols)),
        )
        return int(cur.lastrowid)


def list_events(user_id: int) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE user_id = ? ORDER BY event_date", (user_id,)
        ).fetchall()
    return [_decode(r) for r in rows]


def get_event(user_id: int, event_id: int) -> dict[str, Any] | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM events WHERE id = ? AND user_id = ?", (event_id, user_id)
        ).fetchone()
    return _decode(row) if row else None


def update_event(user_id: int, event_id: int, fields: dict[str, Any]) -> None:
    """Update whitelisted columns only; JSON fields are serialised here."""
    assignments: dict[str, Any] = {c: fields[c] for c in fields.keys() & EDITABLE}
    for key, column in JSON_COLUMNS.items():
        if key in fields:
            assignments[column] = json.dumps(fields[key])
    if not assignments:
        return
    cols = sorted(assignments)
    with _conn() as conn:
        conn.execute(
            f"UPDATE events SET {', '.join(f'{c} = ?' for c in cols)} "
            "WHERE id = ? AND user_id = ?",
            (*(assignments[c] for c in cols), event_id, user_id),
        )


def delete_event(user_id: int, event_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM events WHERE id = ? AND user_id = ?", (event_id, user_id))
        return cur.rowcount > 0


# ── AI artwork (binary, so kept out of the event row) ───────────────────
def save_art(event_id: int, key: str, mime: str, data: bytes) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO artwork (event_id, key, mime, data) VALUES (?, ?, ?, ?)",
            (event_id, key, mime, data),
        )


def get_art(event_id: int, key: str) -> tuple[str, bytes] | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT mime, data FROM artwork WHERE event_id = ? AND key = ?", (event_id, key)
        ).fetchone()
    return (row["mime"], row["data"]) if row else None


def art_keys(event_id: int) -> list[str]:
    with _conn() as conn:
        rows = conn.execute("SELECT key FROM artwork WHERE event_id = ?", (event_id,)).fetchall()
    return [r["key"] for r in rows]


def clear_art(event_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM artwork WHERE event_id = ?", (event_id,))


if settings.store == "firestore":  # production backend; identical function signatures
    from . import store_firestore as _firestore

    for _name in ("init_db", "create_user", "get_user_by_email", "create_session",
                  "get_session_user", "delete_session", "create_event", "list_events",
                  "get_event", "update_event", "delete_event", "save_art", "get_art",
                  "art_keys", "clear_art"):
        globals()[_name] = getattr(_firestore, _name)
