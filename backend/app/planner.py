"""Deterministic planning engine.

Every number Utsav shows — budget lines, due dates, the health score — is
computed here, never by the LLM. The model only writes ideas and prose around
these figures, so a hallucination can never put a wrong rupee amount or a
missed booking deadline in front of a user.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class Task:
    category: str
    title: str
    lead_days: int  # ideal days before the event to have this done
    vendor: bool = False
    custom: bool = False  # added for this event from the user's brief

    @property
    def id(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")
        return f"c-{slug}" if self.custom else slug


# Budget shares are typical market splits; Contingency absorbs rounding.
# min_per_guest is a realistic floor (in INR) below which the plan is flagged;
# other currencies scale it by MARKETS.
PROFILES: dict[str, dict[str, Any]] = {
    "wedding": {
        "label": "Wedding",
        "min_per_guest": 2500,
        "split": {
            "Venue": 0.22,
            "Catering": 0.30,
            "Decor & florals": 0.12,
            "Photography & video": 0.09,
            "Attire & beauty": 0.09,
            "Music & entertainment": 0.05,
            "Invitations & gifts": 0.04,
            "Transport & stay": 0.03,
            "Contingency": 0.06,
        },
        "tasks": [
            Task("Venue", "Shortlist and book the venue", 180, True),
            Task("Photography & video", "Book photographer and videographer", 150, True),
            Task("Catering", "Finalise caterer after a tasting", 120, True),
            Task("Attire & beauty", "Book the makeup artist", 120, True),
            Task("Transport & stay", "Block hotel rooms for outstation guests", 100, True),
            Task("Decor & florals", "Book decorator and approve the mood board", 90, True),
            Task("Music & entertainment", "Book DJ, band or live entertainment", 90, True),
            Task("Attire & beauty", "Order outfits and plan fittings", 90),
            Task("Invitations & gifts", "Send save-the-dates", 75),
            Task("Invitations & gifts", "Print and send invitations", 45, True),
            Task("Catering", "Lock the menu and bar plan", 30),
            Task("Transport & stay", "Arrange guest transport and shuttles", 21, True),
            Task("Invitations & gifts", "Pack return gifts and welcome hampers", 10),
            Task("Catering", "Give the caterer the final headcount", 7),
            Task("Venue", "Share the day-of run sheet with all vendors", 3),
            Task("Contingency", "Prepare the emergency kit and vendor payment envelopes", 1),
        ],
    },
    "birthday": {
        "label": "Birthday",
        "min_per_guest": 600,
        "split": {
            "Venue": 0.22,
            "Food & cake": 0.35,
            "Decor": 0.14,
            "Entertainment": 0.12,
            "Return gifts": 0.06,
            "Photography": 0.05,
            "Contingency": 0.06,
        },
        "tasks": [
            Task("Venue", "Book the venue or reserve the space", 30, True),
            Task("Entertainment", "Book entertainer, games host or DJ", 21, True),
            Task("Decor", "Pick a theme and book the decorator", 21, True),
            Task("Venue", "Send invitations and track RSVPs", 18),
            Task("Photography", "Book a photographer", 14, True),
            Task("Food & cake", "Order the cake", 10, True),
            Task("Food & cake", "Confirm food order with final headcount", 5, True),
            Task("Return gifts", "Buy and pack return gifts", 4),
            Task("Contingency", "Make a playlist and day-of schedule", 2),
        ],
    },
    "community": {
        "label": "Community event",
        "min_per_guest": 200,
        "split": {
            "Venue & permits": 0.20,
            "Food & refreshments": 0.24,
            "Sound & stage": 0.15,
            "Decor": 0.08,
            "Publicity": 0.08,
            "Safety & first aid": 0.06,
            "Volunteers & logistics": 0.08,
            "Sanitation": 0.05,
            "Contingency": 0.06,
        },
        "tasks": [
            Task("Venue & permits", "Book the ground or hall", 60, True),
            Task("Venue & permits", "Apply for local authority and police permissions", 45),
            Task("Publicity", "Reach out to sponsors and local businesses", 45),
            Task("Sound & stage", "Book sound, lights and stage", 30, True),
            Task("Safety & first aid", "Arrange first-aid desk and fire safety", 30, True),
            Task("Volunteers & logistics", "Recruit volunteers and assign roles", 28),
            Task("Food & refreshments", "Book food stalls or a caterer", 21, True),
            Task("Publicity", "Launch posters and social media", 21),
            Task("Sanitation", "Book portable toilets and waste bins", 14, True),
            Task("Decor", "Finalise decor and signage", 10, True),
            Task("Volunteers & logistics", "Brief volunteers and walk the site", 3),
            Task("Contingency", "Prepare a rain plan and emergency contacts", 2),
        ],
    },
}


# Currency symbol and a rough local event-cost factor relative to INR (not an FX rate:
# a wedding guest costs ~₹2,500 in India but ~$150 in the US).
# shortcut: one factor per currency; upgrade to per-city cost data for production.
MARKETS: dict[str, tuple[str, float]] = {
    "INR": ("₹", 1.0), "USD": ("$", 0.06), "EUR": ("€", 0.055), "GBP": ("£", 0.048),
    "AED": ("AED ", 0.22), "SAR": ("SAR ", 0.22), "SGD": ("S$", 0.08), "AUD": ("A$", 0.09),
    "CAD": ("C$", 0.08), "NZD": ("NZ$", 0.09), "JPY": ("¥", 8.0), "CHF": ("CHF ", 0.06),
    "ZAR": ("R", 0.6), "NGN": ("₦", 30.0), "KES": ("KSh ", 4.0), "BRL": ("R$", 0.25),
    "MXN": ("MX$", 0.9), "LKR": ("Rs ", 6.0), "NPR": ("Rs ", 1.4), "BDT": ("৳", 1.2),
}


def money(amount: int, currency: str = "INR") -> str:
    """Format a whole-unit amount: Indian grouping for INR, Western grouping otherwise."""
    if currency == "INR":
        return inr(amount)
    symbol = MARKETS.get(currency, (f"{currency} ", 1.0))[0]
    return ("-" if amount < 0 else "") + f"{symbol}{abs(int(amount)):,}"


def benchmark(kind: str, currency: str = "INR") -> int:
    """Typical minimum spend per guest in the event's currency, to 2 significant figures."""
    value = PROFILES[kind]["min_per_guest"] * MARKETS.get(currency, ("", 1.0))[1]
    return max(1, int(float(f"{value:.2g}")))


def inr(amount: int) -> str:
    """Format rupees with Indian digit grouping: 1234567 -> ₹12,34,567."""
    digits = str(abs(int(amount)))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join([*groups, tail])
    return ("-" if amount < 0 else "") + "₹" + digits


def allocate(total: int, split: dict[str, float]) -> dict[str, int]:
    """Split a budget into whole rupees that sum exactly to `total`."""
    lines = {category: int(total * share) for category, share in split.items()}
    lines["Contingency"] += total - sum(lines.values())
    return lines


PLANNING = "Planning"  # task-only group for coordination work that has no budget line
FULL_CHECKLIST = 8  # an AI task list this long replaces the standard checklist entirely


def task_categories(split: dict[str, float]) -> set[str]:
    """Groups a checklist task may belong to: the event's budget categories plus Planning."""
    return {*split, PLANNING}


def standard_ids(kind: str) -> set[str]:
    return {t.id for t in PROFILES[kind]["tasks"]}


def event_tasks(event: dict[str, Any]) -> list[Task]:
    """Standard checklist for the event type, minus tasks the brief made irrelevant,
    plus tasks personalised from the brief."""
    skipped = set(event.get("skipped") or [])
    standard = [t for t in PROFILES[event["kind"]]["tasks"] if t.id not in skipped]
    custom = [
        Task(t["category"], t["title"], int(t["lead_days"]), bool(t.get("vendor")), custom=True)
        for t in event.get("custom_tasks") or []
    ]
    return [*standard, *custom]


def task_ids(event: dict[str, Any]) -> set[str]:
    return {t.id for t in event_tasks(event)}


def event_split(event: dict[str, Any]) -> dict[str, float]:
    return event.get("split_override") or PROFILES[event["kind"]]["split"]


MAX_CATEGORIES = 12


def clean_split(kind: str, raw: Any) -> dict[str, float] | None:
    """Validate a proposed budget split.

    Three or more named categories are an event-specific set designed by the AI (any
    names, up to 12). Fewer are a tilt of the standard split for the event type (unknown
    names dropped, missing ones keep their default). Either way: positive shares only,
    Contingency always present (last) and never below 4%, shares normalised to 1.
    """
    if not isinstance(raw, dict):
        return None
    proposed: dict[str, float] = {}
    for name, value in raw.items():
        valid = (isinstance(name, str) and isinstance(value, (int, float))
                 and not isinstance(value, bool) and 0 < value <= 0.8)
        label = " ".join(str(name).split())[:30]
        if not valid or not label:
            continue
        label = "Contingency" if label.lower() == "contingency" else label
        if label in proposed or len(proposed) < MAX_CATEGORIES:
            proposed[label] = proposed.get(label, 0.0) + float(value)
    if len([c for c in proposed if c != "Contingency"]) < 3:
        base = PROFILES[kind]["split"]
        proposed = {cat: proposed.get(cat, default) for cat, default in base.items()}
    contingency = max(proposed.pop("Contingency", 0.0), 0.04)
    total = sum(proposed.values()) + contingency
    split = {cat: round(v / total, 4) for cat, v in proposed.items()}
    split["Contingency"] = round(contingency / total, 4)
    return split


def _status(due: date, today: date, done: bool) -> str:
    if done:
        return "done"
    if due < today:
        return "late"
    return "soon" if (due - today).days <= 14 else "upcoming"


def build_plan(event: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    profile = PROFILES[event["kind"]]
    currency = event.get("currency") or "INR"
    event_date = date.fromisoformat(event["event_date"])
    done = set(event.get("done") or [])
    spend = event.get("spend") or {}

    planned = allocate(event["budget"], event_split(event))
    lines = [
        {
            "category": cat,
            "planned": amount,
            "spent": int(spend.get(cat, 0)),
            "remaining": amount - int(spend.get(cat, 0)),
        }
        for cat, amount in planned.items()
    ]
    spent = sum(line["spent"] for line in lines)

    tasks = []
    for task in event_tasks(event):
        due = event_date - timedelta(days=task.lead_days)
        tasks.append(
            {
                "id": task.id,
                "category": task.category,
                "title": task.title,
                "vendor": task.vendor,
                "custom": task.custom,
                "lead_days": task.lead_days,
                "due": due.isoformat(),
                "status": _status(due, today, task.id in done),
            }
        )
    tasks.sort(key=lambda t: t["due"])
    # Rescue plan: late tasks, longest-lead first (they're hardest to recover).
    late = sorted((t for t in tasks if t["status"] == "late"), key=lambda t: -t["lead_days"])

    return {
        "days_left": (event_date - today).days,
        "budget": {
            "total": event["budget"],
            "spent": spent,
            "remaining": event["budget"] - spent,
            "per_guest": event["budget"] // event["guests"],
            "benchmark_per_guest": benchmark(event["kind"], currency),
            "currency": currency,
            "designed": bool(event.get("split_override")),  # categories tailored from the brief
            "lines": lines,
        },
        "tasks": tasks,
        "rescue": [t["id"] for t in late[:5]],
        "ai_checklist": not any(not t["custom"] for t in tasks),
        "progress": round(sum(t["status"] == "done" for t in tasks) / len(tasks), 2),
        "health": _health(event, profile, currency, lines, tasks, late),
    }


def _health(
    event: dict[str, Any],
    profile: dict[str, Any],
    currency: str,
    lines: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    late: list[dict[str, Any]],
) -> dict[str, Any]:
    notes: list[str] = []
    fmt = lambda n: money(n, currency)  # noqa: E731
    per_guest_floor = benchmark(event["kind"], currency)
    floor = event["guests"] * per_guest_floor
    # Squared so a real shortfall drags the score down faster than a linear ratio would.
    budget_score = min(event["budget"] / floor, 1.0) ** 2
    if budget_score < 1:
        notes.append(
            f"Budget works out to {fmt(event['budget'] // event['guests'])} per guest; a "
            f"{profile['label'].lower()} typically needs about {fmt(per_guest_floor)}. "
            f"Trim the list to {event['budget'] // per_guest_floor} guests or add "
            f"{fmt(floor - event['budget'])}."
        )

    open_tasks = [t for t in tasks if t["status"] != "done"]
    time_score = 1 - len(late) / len(open_tasks) if open_tasks else 1.0
    if late:
        notes.append(
            f"{len(late)} task(s) are past their ideal date. Start with: {late[0]['title']}."
        )

    over = [line for line in lines if line["remaining"] < 0 and line["category"] != "Contingency"]
    for line in over:
        notes.append(f"{line['category']} is {fmt(-line['remaining'])} over plan.")
    total_spent = sum(line["spent"] for line in lines)
    penalty = 15 if total_spent > event["budget"] else 5 * min(len(over), 2)
    if total_spent > event["budget"]:
        notes.append(f"Total spend is {fmt(total_spent - event['budget'])} over the budget.")

    score = max(0, min(100, round(100 * (0.5 * budget_score + 0.5 * time_score)) - penalty))
    label = "On track" if score >= 80 else "Needs attention" if score >= 55 else "At risk"
    if not notes:
        notes.append("Budget and timeline look healthy. Keep ticking off the checklist.")
    return {"score": score, "label": label, "notes": notes}


def to_ics(event: dict[str, Any], plan: dict[str, Any]) -> str:
    """Export open tasks + the event itself as an iCalendar file."""

    def esc(text: str) -> str:
        return re.sub(r"([,;\\])", r"\\\1", text).replace("\n", "\\n")

    def vevent(uid: str, day: str, summary: str) -> list[str]:
        start = date.fromisoformat(day)
        return [
            "BEGIN:VEVENT",
            f"UID:{uid}@utsav",
            f"DTSTAMP:{date.today():%Y%m%d}T000000Z",
            f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
            f"DTEND;VALUE=DATE:{start + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{esc(summary)}",
            "END:VEVENT",
        ]

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Utsav//Event Planner//EN"]
    lines += vevent(f"event-{event['id']}", event["event_date"], f"🎉 {event['name']}")
    for task in plan["tasks"]:
        if task["status"] != "done":
            due = max(task["due"], date.today().isoformat())  # late tasks land on today
            lines += vevent(f"{event['id']}-{task['id']}", due, f"{event['name']}: {task['title']}")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
