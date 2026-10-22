from datetime import date, timedelta

import pytest
from backend.app.planner import PROFILES, allocate, build_plan, inr, task_ids, to_ics

TODAY = date(2026, 1, 1)


def _event(**kw):
    base = {
        "id": 1, "name": "Test", "kind": "wedding", "guests": 100, "budget": 500_000,
        "event_date": (TODAY + timedelta(days=200)).isoformat(), "done": [], "spend": {},
    }
    return {**base, **kw}


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(0, "₹0"), (999, "₹999"), (1000, "₹1,000"), (123456, "₹1,23,456"),
     (12345678, "₹1,23,45,678"), (-5000, "-₹5,000")],
)
def test_inr_uses_indian_grouping(amount, expected):
    assert inr(amount) == expected


@pytest.mark.parametrize("kind", PROFILES)
def test_profiles_are_consistent(kind):
    profile = PROFILES[kind]
    assert abs(sum(profile["split"].values()) - 1.0) < 1e-9
    assert "Contingency" in profile["split"]
    assert len(task_ids({"kind": kind})) == len(profile["tasks"])  # ids unique
    assert {t.category for t in profile["tasks"]} <= set(profile["split"])


@pytest.mark.parametrize("total", [1000, 99_999, 1_500_001, 7])
def test_allocation_sums_exactly(total):
    assert sum(allocate(total, PROFILES["wedding"]["split"]).values()) == total


def test_task_statuses_follow_dates():
    plan = build_plan(_event(event_date=(TODAY + timedelta(days=100)).isoformat()), TODAY)
    by_title = {t["title"]: t for t in plan["tasks"]}
    assert by_title["Shortlist and book the venue"]["status"] == "late"  # 180-day lead
    assert by_title["Lock the menu and bar plan"]["status"] == "upcoming"
    assert plan["rescue"][0] == "shortlist-and-book-the-venue"  # longest lead first
    assert [t["due"] for t in plan["tasks"]] == sorted(t["due"] for t in plan["tasks"])


def test_done_tasks_count_towards_progress():
    ids = sorted(task_ids({"kind": "birthday"}))
    plan = build_plan(_event(kind="birthday", done=ids[:3]), TODAY)
    assert plan["progress"] == round(3 / len(ids), 2)
    assert sum(t["status"] == "done" for t in plan["tasks"]) == 3


def test_healthy_plan_scores_high():
    plan = build_plan(_event(), TODAY)
    assert plan["health"]["label"] == "On track"
    assert plan["health"]["score"] >= 80


def test_thin_budget_gives_actionable_note():
    plan = build_plan(_event(budget=100_000, guests=100), TODAY)  # ₹1,000/guest vs ₹2,500
    note = plan["health"]["notes"][0]
    assert "40 guests" in note and "₹1,50,000" in note
    assert plan["health"]["score"] < 80


def test_overspend_is_flagged_and_penalised():
    healthy = build_plan(_event(), TODAY)["health"]["score"]
    plan = build_plan(_event(spend={"Catering": 600_000}), TODAY)
    assert any("Catering is" in n for n in plan["health"]["notes"])
    assert any("over the budget" in n for n in plan["health"]["notes"])
    assert plan["health"]["score"] == healthy - 15
    assert plan["budget"]["remaining"] == -100_000


def test_ics_export_is_valid_calendar():
    event = _event(done=["shortlist-and-book-the-venue"])
    ics = to_ics(event, build_plan(event, TODAY))
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == len(PROFILES["wedding"]["tasks"])  # -1 done, +1 event
    assert "book the venue" not in ics


def test_money_formats_per_currency():
    from backend.app.planner import money
    assert money(1234567, "INR") == "₹12,34,567"
    assert money(1234567, "USD") == "$1,234,567"
    assert money(-500, "EUR") == "-€500"
    assert money(2000, "AED") == "AED 2,000"


def test_benchmark_scales_to_local_market():
    from backend.app.planner import benchmark
    assert benchmark("wedding", "INR") == 2500
    assert benchmark("wedding", "USD") == 150
    plan = build_plan(_event(currency="USD", budget=10_000, guests=100), TODAY)
    assert plan["budget"]["benchmark_per_guest"] == 150
    assert "$100 per guest" in plan["health"]["notes"][0]


def test_clean_split_validates_and_normalises():
    from backend.app.planner import clean_split
    split = clean_split("birthday", {"Entertainment": 0.4, "Contingency": 0.0, "Bogus": 0.9})
    assert abs(sum(split.values()) - 1) < 0.001 and "Bogus" not in split
    assert split["Contingency"] >= 0.03  # floor of 4% before normalising
    assert split["Entertainment"] > split["Decor"]
    assert clean_split("birthday", "nope") is None


def test_custom_tasks_and_split_flow_into_plan():
    event = _event(
        custom_tasks=[{"title": "Book a henna artist", "category": "Attire & beauty",
                       "lead_days": 30, "vendor": True}],
        split_override={**PROFILES["wedding"]["split"], "Catering": 0.5},
    )
    plan = build_plan(event, TODAY)
    custom = [t for t in plan["tasks"] if t["custom"]]
    assert custom[0]["id"] == "c-book-a-henna-artist"
    assert "c-book-a-henna-artist" in task_ids(event)
    assert sum(line["planned"] for line in plan["budget"]["lines"]) == event["budget"]


def test_ai_designed_categories_replace_the_standard_set():
    from backend.app.planner import clean_split
    split = clean_split("community", {
        "Food & prasad": 0.45, "Puja samagri": 0.15, "Mehndi artists": 0.1,
        "Decor & lighting": 0.2, "  Terrace   setup ": 0.05, "contingency": 0.0, "Bad": "x"})
    assert list(split) == ["Food & prasad", "Puja samagri", "Mehndi artists",
                           "Decor & lighting", "Terrace setup", "Contingency"]
    assert split["Contingency"] >= 0.03 and abs(sum(split.values()) - 1) < 0.001
    plan = build_plan(_event(kind="community", split_override=split,
                             skipped=["book-the-ground-or-hall"]), TODAY)
    assert [ln["category"] for ln in plan["budget"]["lines"]][-1] == "Contingency"
    assert sum(ln["planned"] for ln in plan["budget"]["lines"]) == 500_000
    assert "book-the-ground-or-hall" not in {t["id"] for t in plan["tasks"]}
