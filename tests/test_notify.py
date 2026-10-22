from datetime import date, timedelta

from backend.app.notify import PRIORITIES, build_notifications
from backend.app.planner import build_plan, task_ids

TODAY = date(2026, 1, 1)


def _notes(days_left=200, **kw):
    event = {
        "id": 7, "name": "Test", "kind": "wedding", "guests": 100, "budget": 500_000,
        "event_date": (TODAY + timedelta(days=days_left)).isoformat(),
        "done": [], "spend": {}, "ideas": None, **kw,
    }
    return build_notifications(event, build_plan(event, TODAY), TODAY)


def _keys(notes):
    return {n["id"].split(":", 1)[1]: n["priority"] for n in notes}


def test_healthy_far_event_only_suggests_ideas():
    keys = _keys(_notes())
    assert keys == {"ideas": "low"}


def test_countdown_milestones():
    assert _keys(_notes(days_left=0))["today"] == "critical"
    assert _keys(_notes(days_left=1))["tomorrow"] == "high"
    assert _keys(_notes(days_left=5))["final-week"] == "high"
    assert _keys(_notes(days_left=20))["month"] == "medium"
    assert _keys(_notes(days_left=-3))["past"] == "low"


def test_overdue_vendor_task_is_critical_and_triggers_rescue():
    keys = _keys(_notes(days_left=100))  # 3 of 16 late: below the rescue threshold
    assert keys["task:shortlist-and-book-the-venue:late"] == "critical"
    assert "rescue" not in keys
    assert _keys(_notes(days_left=80))["rescue"] == "critical"  # 8 of 16 late


def test_upcoming_tasks_scale_with_proximity():
    # Wedding "Lock the menu" is 30 days before; "final headcount" 7 days before.
    keys = _keys(_notes(days_left=31))  # menu due in 1 day
    assert keys["task:lock-the-menu-and-bar-plan:3d"] == "high"
    keys = _keys(_notes(days_left=36))  # menu due in 6 days
    assert keys["task:lock-the-menu-and-bar-plan:7d"] == "medium"
    keys = _keys(_notes(days_left=40))  # menu due in 10 days
    assert keys["task:lock-the-menu-and-bar-plan:14d"] == "low"
    keys = _keys(_notes(days_left=30))
    assert keys["task:lock-the-menu-and-bar-plan:today"] == "high"


def test_budget_alerts():
    keys = _keys(_notes(spend={"Catering": 600_000}))
    assert keys["over-total"] == "critical"
    assert keys["over:catering"] == "high"
    keys = _keys(_notes(spend={"Venue": 105_000}))  # 95% of 110,000
    assert keys["near:venue"] == "medium"
    assert _keys(_notes(budget=150_000))["thin-budget"] == "high"   # 60% of benchmark
    assert _keys(_notes(budget=220_000))["thin-budget"] == "medium"  # 88%


def test_all_done_and_ideas_present():
    keys = _keys(_notes(done=sorted(task_ids({"kind": "wedding"})), ideas={"theme": "x"}))
    assert keys == {"all-done": "low"}


def test_sorted_most_urgent_first():
    notes = _notes(days_left=100, spend={"Catering": 600_000})
    ranks = [PRIORITIES.index(n["priority"]) for n in notes]
    assert ranks == sorted(ranks)


def test_brief_alerts_show_in_their_window_and_go_stale_with_the_brief():
    alerts = {"brief": "Karwa Chauth for residents", "source": "gemini", "items": [
        {"title": "Collect ₹600 contributions", "message": "Start collecting from residents.",
         "priority": "high", "days_before": 10, "tab": "budget"},
        {"title": "Confirm moonrise time", "message": "Check a local panchang.",
         "priority": "medium", "days_before": 2, "tab": "timeline"}]}
    kw = {"brief": "Karwa Chauth for residents", "brief_alerts": alerts}
    keys = _keys(_notes(days_left=7, **kw))
    assert keys["brief:collect-600-contributions"] == "high"
    assert "brief:confirm-moonrise-time" not in keys  # its window hasn't opened yet
    assert _keys(_notes(days_left=1, **kw))["brief:confirm-moonrise-time"] == "high"  # eve bump
    stale = _keys(_notes(days_left=7, brief="New brief text", brief_alerts=alerts))
    assert not any(k.startswith("brief:") for k in stale)
