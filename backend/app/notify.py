"""Deterministic notifications: what needs attention, how urgently, and why.

Derived from the computed plan on every request (nothing stored), so alerts
always match the current dates, checklist and spend. Ids encode the state that
triggered them, so a dismissed alert comes back if the situation changes
(e.g. "due in 3 days" -> "due today").
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from .planner import money

PRIORITIES = ("critical", "high", "medium", "low")


def urgency(note: dict[str, Any]) -> tuple[int, int]:
    """Sort key: priority first, then the soonest/most overdue date."""
    due_in = note["due_in"] if note["due_in"] is not None else 10_000
    return PRIORITIES.index(note["priority"]), due_in


def _days(n: int) -> str:
    return f"{n} day" if abs(n) == 1 else f"{n} days"


def build_notifications(
    event: dict[str, Any], plan: dict[str, Any], today: date | None = None
) -> list[dict[str, Any]]:
    today = today or date.today()
    out: list[dict[str, Any]] = []

    def add(key: str, priority: str, title: str, message: str, tab: str, due_in: int | None = None):
        out.append(
            {
                "id": f"{event['id']}:{key}",
                "event_id": event["id"],
                "event_name": event["name"],
                "priority": priority,
                "title": title,
                "message": message,
                "tab": tab,
                "due_in": due_in,
            }
        )

    # ── event countdown ──
    left = plan["days_left"]
    if left < 0:
        add("past", "low", "Event has passed",
            f"{event['name']} was {_days(-left)} ago. Close out final payments.", "budget", left)
    elif left == 0:
        add("today", "critical", "It's event day!",
            "Keep the run sheet and vendor contacts handy. Enjoy it!", "timeline", 0)
    elif left == 1:
        add("tomorrow", "high", "Event is tomorrow",
            "Confirm timings with every vendor and charge your phone.", "timeline", 1)
    elif left <= 7:
        add("final-week", "high", "Final week",
            f"{_days(left)} to go. Reconfirm vendors and the final headcount.", "timeline", left)
    elif left <= 30:
        add("month", "medium", "Less than a month to go",
            f"{_days(left)} left. Lock the menu, decor and guest list.", "timeline", left)

    # ── tasks ──
    open_tasks = [t for t in plan["tasks"] if t["status"] != "done"]
    late = [t for t in open_tasks if t["status"] == "late"]
    if open_tasks and len(late) / len(open_tasks) >= 0.3:
        add("rescue", "critical", "Timeline at risk",
            f"{len(late)} of {len(open_tasks)} open tasks are overdue. Follow the rescue plan.",
            "timeline")
    for task in open_tasks:
        due_in = (date.fromisoformat(task["due"]) - today).days
        if due_in < 0:
            overdue = -due_in
            priority = "critical" if task["vendor"] or overdue > 14 else "high"
            add(f"task:{task['id']}:late", priority, f"Overdue: {task['title']}",
                f"Was due {_days(overdue)} ago. Good {task['category'].lower()} "
                "vendors book out early, so act now.", "checklist", due_in)
        elif due_in == 0:
            add(f"task:{task['id']}:today", "high", f"Due today: {task['title']}",
                f"{task['category']} task due today.", "checklist", 0)
        elif due_in <= 3:
            add(f"task:{task['id']}:3d", "high", f"Due in {_days(due_in)}: {task['title']}",
                f"{task['category']} task coming up fast.", "checklist", due_in)
        elif due_in <= 7:
            add(f"task:{task['id']}:7d", "medium", f"Due this week: {task['title']}",
                f"Due in {_days(due_in)} ({task['due']}).", "checklist", due_in)
        elif due_in <= 14:
            add(f"task:{task['id']}:14d", "low", f"Coming up: {task['title']}",
                f"Due in {_days(due_in)} ({task['due']}).", "checklist", due_in)
    if not open_tasks:
        add("all-done", "low", "Checklist complete",
            "Every task is done. Time to relax and celebrate!", "checklist")

    # ── budget ──
    budget = plan["budget"]
    fmt = lambda n: money(n, budget["currency"])  # noqa: E731
    if budget["spent"] > budget["total"]:
        add("over-total", "critical", "Over total budget",
            f"Spending is {fmt(budget['spent'] - budget['total'])} over the "
            f"{fmt(budget['total'])} budget.", "budget")
    for line in budget["lines"]:
        if line["category"] == "Contingency" or not line["planned"]:
            continue
        slug = line["category"].lower().replace(" ", "-")
        if line["remaining"] < 0:
            add(f"over:{slug}", "high", f"{line['category']} over plan",
                f"{fmt(-line['remaining'])} over its {fmt(line['planned'])} allocation. "
                "Move money from contingency or trim elsewhere.", "budget")
        elif line["spent"] >= 0.9 * line["planned"]:
            add(f"near:{slug}", "medium", f"{line['category']} almost used up",
                f"{fmt(line['remaining'])} left of {fmt(line['planned'])}.", "budget")
    ratio = budget["per_guest"] / budget["benchmark_per_guest"]
    if ratio < 1:
        add("thin-budget", "high" if ratio < 0.7 else "medium",
            "Budget is tight for the guest count",
            f"{fmt(budget['per_guest'])} per guest vs a typical "
            f"{fmt(budget['benchmark_per_guest'])}. Use What-if to try a smaller list.", "budget")

    # ── smart alerts written from the brief: each shows from its own window onwards ──
    alerts = event.get("brief_alerts") or {}
    if left >= 0 and alerts.get("brief") == event.get("brief"):  # stale once the brief changes
        for alert in alerts.get("items", []):
            if left <= alert["days_before"]:
                slug = re.sub(r"[^a-z0-9]+", "-", alert["title"].lower()).strip("-")
                priority = alert["priority"]
                if left <= 1 and priority in ("medium", "low"):
                    priority = "high"  # anything still open on the eve becomes pressing
                add(f"brief:{slug}", priority, alert["title"], alert["message"], alert["tab"])
                out[-1]["source"] = "brief"

    # ── ideas ──
    if not event.get("ideas") and left >= 0:
        add("ideas", "low", "Get your theme ideas",
            "Generate a theme, palette, menu and activities tailored to your event.", "ideas")

    out.sort(key=urgency)
    return out
