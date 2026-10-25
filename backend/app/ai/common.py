"""Shared helpers for the GenAI modules: the event facts every prompt receives."""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from ..planner import (
    PROFILES,
    money,
)

IDEA_KEYS = ("decor", "food", "activities", "personal_touches", "sustainability")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

def _event_data(event: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": PROFILES[event["kind"]]["label"],
        "name": event["name"],
        "city": event["city"],
        "guests": event["guests"],
        "budget_per_guest": money(plan["budget"]["per_guest"], plan["budget"]["currency"]),
        "days_until_event": plan["days_left"],
        "vibe": event["vibe"],
        "tradition": event["tradition"],
        "brief": (event.get("brief") or "")[:1500],
        "budget_categories": [line["category"] for line in plan["budget"]["lines"]],
    }


def _event_block(event: dict[str, Any], plan: dict[str, Any]) -> str:
    return f"<event>{json.dumps(_event_data(event, plan), ensure_ascii=False)}</event>"

def clean_strings(value: Any, limit: int, size: int) -> list[str]:
    """Up to `limit` non-empty, trimmed strings (each at most `size` chars) from a model list."""
    items = value if isinstance(value, list) else []
    return [str(x).strip()[:size] for x in items if str(x).strip()][:limit]


def pretty_date(iso: str) -> str:
    """Format an ISO date for people, e.g. 'Saturday, 12 June 2027'."""
    d = date.fromisoformat(iso)
    return f"{d:%A}, {d.day} {d:%B %Y}"
