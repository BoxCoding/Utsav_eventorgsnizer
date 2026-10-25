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


Alert = dict[str, Any]


def _alert(key: str, priority: str, title: str, message: str, tab: str,
           due_in: int | None = None, **extra: Any) -> Alert:
    return {"key": key, "priority": priority, "title": title, "message": message,
            "tab": tab, "due_in": due_in, **extra}


def build_notifications(
    event: dict[str, Any], plan: dict[str, Any], today: date | None = None
) -> list[Alert]:
    """Every alert for one event, most urgent first (see the module docstring)."""
    today = today or date.today()
    left = plan["days_left"]
    alerts = [
        *_countdown_alerts(event, left),
        *_task_alerts(plan["tasks"], today),
        *_budget_alerts(plan["budget"]),
        *_brief_alerts(event, left),
        *_ideas_alerts(event, left),
    ]
    notes = [
        {"id": f"{event['id']}:{a.pop('key')}", "event_id": event["id"],
         "event_name": event["name"], **a}
        for a in alerts
    ]
    return sorted(notes, key=urgency)


def _countdown_alerts(event: dict[str, Any], left: int) -> list[Alert]:
    if left < 0:
        return [_alert("past", "low", "Event has passed",
                       f"{event['name']} was {_days(-left)} ago. Close out final payments.",
                       "budget", left)]
    if left == 0:
        return [_alert("today", "critical", "It's event day!",
                       "Keep the run sheet and vendor contacts handy. Enjoy it!", "timeline", 0)]
    if left == 1:
        return [_alert("tomorrow", "high", "Event is tomorrow",
                       "Confirm timings with every vendor and charge your phone.", "timeline", 1)]
    if left <= 7:
        return [_alert("final-week", "high", "Final week",
                       f"{_days(left)} to go. Reconfirm vendors and the final headcount.",
                       "timeline", left)]
    if left <= 30:
        return [_alert("month", "medium", "Less than a month to go",
                       f"{_days(left)} left. Lock the menu, decor and guest list.",
                       "timeline", left)]
    return []


def _task_alerts(tasks: list[dict[str, Any]], today: date) -> list[Alert]:
    open_tasks = [t for t in tasks if t["status"] != "done"]
    if not open_tasks:
        return [_alert("all-done", "low", "Checklist complete",
                       "Every task is done. Time to relax and celebrate!", "checklist")]
    alerts = []
    late = [t for t in open_tasks if t["status"] == "late"]
    if len(late) / len(open_tasks) >= 0.3:
        alerts.append(_alert(
            "rescue", "critical", "Timeline at risk",
            f"{len(late)} of {len(open_tasks)} open tasks are overdue. Follow the rescue plan.",
            "timeline"))
    for task in open_tasks:
        alert = _task_due_alert(task, (date.fromisoformat(task["due"]) - today).days)
        if alert:
            alerts.append(alert)
    return alerts


def _task_due_alert(task: dict[str, Any], due_in: int) -> Alert | None:
    key, title = f"task:{task['id']}", task["title"]
    if due_in < 0:
        overdue = -due_in
        priority = "critical" if task["vendor"] or overdue > 14 else "high"
        return _alert(f"{key}:late", priority, f"Overdue: {title}",
                      f"Was due {_days(overdue)} ago. Good {task['category'].lower()} "
                      "vendors book out early, so act now.", "checklist", due_in)
    if due_in == 0:
        return _alert(f"{key}:today", "high", f"Due today: {title}",
                      f"{task['category']} task due today.", "checklist", 0)
    if due_in <= 3:
        return _alert(f"{key}:3d", "high", f"Due in {_days(due_in)}: {title}",
                      f"{task['category']} task coming up fast.", "checklist", due_in)
    if due_in <= 7:
        return _alert(f"{key}:7d", "medium", f"Due this week: {title}",
                      f"Due in {_days(due_in)} ({task['due']}).", "checklist", due_in)
    if due_in <= 14:
        return _alert(f"{key}:14d", "low", f"Coming up: {title}",
                      f"Due in {_days(due_in)} ({task['due']}).", "checklist", due_in)
    return None


def _budget_alerts(budget: dict[str, Any]) -> list[Alert]:
    def fmt(n: int) -> str:
        """Format an amount in the event's currency."""
        return money(n, budget["currency"])

    alerts = []
    if budget["spent"] > budget["total"]:
        alerts.append(_alert("over-total", "critical", "Over total budget",
                             f"Spending is {fmt(budget['spent'] - budget['total'])} over the "
                             f"{fmt(budget['total'])} budget.", "budget"))
    for line in budget["lines"]:
        if line["category"] == "Contingency" or not line["planned"]:
            continue
        slug = line["category"].lower().replace(" ", "-")
        if line["remaining"] < 0:
            alerts.append(_alert(f"over:{slug}", "high", f"{line['category']} over plan",
                                 f"{fmt(-line['remaining'])} over its {fmt(line['planned'])} "
                                 "allocation. Move money from contingency or trim elsewhere.",
                                 "budget"))
        elif line["spent"] >= 0.9 * line["planned"]:
            alerts.append(_alert(f"near:{slug}", "medium", f"{line['category']} almost used up",
                                 f"{fmt(line['remaining'])} left of {fmt(line['planned'])}.",
                                 "budget"))
    ratio = budget["per_guest"] / budget["benchmark_per_guest"]
    if ratio < 1:
        alerts.append(_alert(
            "thin-budget", "high" if ratio < 0.7 else "medium",
            "Budget is tight for the guest count",
            f"{fmt(budget['per_guest'])} per guest vs a typical "
            f"{fmt(budget['benchmark_per_guest'])}. Use What-if to try a smaller list.", "budget"))
    return alerts


def _brief_alerts(event: dict[str, Any], left: int) -> list[Alert]:
    """Smart alerts written from the brief; each shows from its own window onwards."""
    stored = event.get("brief_alerts") or {}
    if left < 0 or stored.get("brief") != event.get("brief"):  # stale once the brief changes
        return []
    alerts = []
    for item in stored.get("items", []):
        if left > item["days_before"]:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", item["title"].lower()).strip("-")
        priority = item["priority"]
        if left <= 1 and priority in ("medium", "low"):
            priority = "high"  # anything still open on the eve becomes pressing
        alerts.append(_alert(f"brief:{slug}", priority, item["title"], item["message"],
                             item["tab"], source="brief"))
    return alerts


def _ideas_alerts(event: dict[str, Any], left: int) -> list[Alert]:
    if event.get("ideas") or left < 0:
        return []
    return [_alert("ideas", "low", "Get your theme ideas",
                   "Generate a theme, palette, menu and activities tailored to your event.",
                   "ideas")]
