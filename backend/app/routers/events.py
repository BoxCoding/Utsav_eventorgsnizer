"""Event CRUD, the computed plan, GenAI ideas, the assistant and calendar export."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .. import ai, store
from ..auth import current_user
from ..gemini_client import LLMUnavailableError, generate_image
from ..notify import build_notifications, urgency
from ..planner import (
    PROFILES,
    assess_budget,
    build_plan,
    clean_split,
    estimate_budget,
    event_split,
    standard_ids,
    task_categories,
    task_ids,
    to_ics,
)
from ..schemas import (
    ArtRequest,
    AskRequest,
    BriefRequest,
    Currency,
    EventIn,
    EventPatch,
    InviteRequest,
    Kind,
)

router = APIRouter(prefix="/api/events", tags=["events"])
notifications_router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _owned(user: dict, event_id: int) -> dict[str, Any]:
    event = store.get_event(user["id"], event_id)
    if event is None:  # 404 (not 403) so ids of other users' events don't leak
        raise HTTPException(status_code=404, detail="event not found")
    return event


def _view(event: dict[str, Any]) -> dict[str, Any]:
    return {"event": event, "plan": build_plan(event)}


@router.get("/profiles")
async def profiles() -> dict:
    """Event types with their budget splits, for the creation form."""
    return {
        kind: {"label": p["label"], "categories": list(p["split"]), "tasks": len(p["tasks"])}
        for kind, p in PROFILES.items()
    }


@router.get("/estimate")
async def estimate(
    kind: Kind,
    guests: int = Query(ge=1, le=10_000),
    currency: Currency = "INR",
    budget: int | None = Query(default=None, ge=0, le=10_000_000_000),
    user: dict = Depends(current_user),
) -> dict:
    """Live budget check for the creation form: suggestion, per-guest spend and verdict."""
    return assess_budget(kind, guests, budget, currency)


@router.get("")
async def list_events(user: dict = Depends(current_user)) -> dict:
    events = store.list_events(user["id"])
    summaries = []
    for event in events:
        plan = build_plan(event)
        summaries.append(
            {
                "id": event["id"],
                "name": event["name"],
                "kind": event["kind"],
                "event_date": event["event_date"],
                "guests": event["guests"],
                "days_left": plan["days_left"],
                "progress": plan["progress"],
                "health": plan["health"]["label"],
                "score": plan["health"]["score"],
            }
        )
    return {"events": summaries}


@router.post("/brief")
async def read_brief(payload: BriefRequest, user: dict = Depends(current_user)) -> dict:
    """Turn a free-text description into form fields, personalised tasks and a budget split.
    Nothing is saved: the user reviews the result before creating the event."""
    return await ai.read_brief(payload.brief, kind=payload.kind)


@router.post("", status_code=201)
async def create_event(payload: EventIn, user: dict = Depends(current_user)) -> dict:
    fields = payload.model_dump()
    fields["event_date"] = payload.event_date.isoformat()
    # AI-proposed extras are re-validated here: tasks must use this event's categories,
    # and only standard tasks of this event type can be skipped.
    fields["split_override"] = clean_split(payload.kind, fields["split_override"])
    categories = task_categories(fields["split_override"] or PROFILES[payload.kind]["split"])
    fields["custom_tasks"] = [t for t in fields["custom_tasks"] if t["category"] in categories]
    fields["skipped"] = sorted(set(fields["skipped"]) & standard_ids(payload.kind))
    if not fields["budget"]:  # never invent a fixed default: size it to this event
        fields["budget"] = estimate_budget(payload.kind, payload.guests, payload.currency)
        fields["budget_note"] = fields["budget_note"] or (
            f"Estimated by Utsav for {payload.guests} guests; adjust it in What-if.")
    event_id = store.create_event(user["id"], fields)
    return _view(_owned(user, event_id))


@router.get("/{event_id}")
async def get_event(event_id: int, user: dict = Depends(current_user)) -> dict:
    return _view(_owned(user, event_id))


@router.patch("/{event_id}")
async def update_event(
    event_id: int, payload: EventPatch, user: dict = Depends(current_user)
) -> dict:
    event = _owned(user, event_id)
    fields = payload.model_dump(exclude_none=True)
    if "event_date" in fields:
        fields["event_date"] = fields["event_date"].isoformat()
    # Keep only ids/categories that exist for this event type.
    if "done" in fields:
        fields["done"] = sorted(set(fields["done"]) & task_ids(event))
    # A re-plan from the brief: same validation as on create. Spend on categories that no
    # longer exist and ticks on tasks that no longer exist are dropped, so totals and
    # progress stay honest.
    if "split_override" in fields:
        fields["split_override"] = clean_split(event["kind"], fields["split_override"])
        if fields["split_override"] is None:
            del fields["split_override"]
    categories = event_split({**event, **fields})  # budget lines; tasks may also use Planning
    if "skipped" in fields:
        fields["skipped"] = sorted(set(fields["skipped"]) & standard_ids(event["kind"]))
    if "custom_tasks" in fields:
        allowed = task_categories(categories)
        fields["custom_tasks"] = [t for t in fields["custom_tasks"] if t["category"] in allowed]
    if {"custom_tasks", "skipped"} & fields.keys():
        new_ids = task_ids({**event, **fields})
        fields["done"] = sorted(set(fields.get("done", event["done"])) & new_ids)
    if "spend" in fields or "split_override" in fields:
        spend = fields.get("spend", event["spend"])
        fields["spend"] = {k: v for k, v in spend.items() if k in categories}
    store.update_event(user["id"], event_id, fields)
    return _view(_owned(user, event_id))


@router.delete("/{event_id}", status_code=204)
async def delete_event(event_id: int, user: dict = Depends(current_user)) -> Response:
    if not store.delete_event(user["id"], event_id):
        raise HTTPException(status_code=404, detail="event not found")
    return Response(status_code=204)


@router.post("/{event_id}/replan")
async def replan(event_id: int, payload: BriefRequest, user: dict = Depends(current_user)) -> dict:
    """Re-read an edited brief against the current plan. Nothing is saved: the client shows
    the proposed changes and PATCHes only what the user accepts."""
    event = _owned(user, event_id)
    return await ai.read_brief(payload.brief, kind=event["kind"], current=ai.current_plan(event))


@router.post("/{event_id}/alerts")
async def brief_alerts(event_id: int, user: dict = Depends(current_user)) -> dict:
    """(Re)generate smart reminders from the brief; the bell shows each in its window."""
    event = _owned(user, event_id)
    alerts = await ai.generate_brief_alerts(event, build_plan(event))
    store.update_event(user["id"], event_id, {"brief_alerts": alerts})
    return {"brief_alerts": alerts}


@router.post("/{event_id}/runsheet")
async def run_sheet(event_id: int, user: dict = Depends(current_user)) -> dict:
    """(Re)draft the day-of schedule with Gemini and save it on the event."""
    event = _owned(user, event_id)
    sheet = await ai.generate_run_sheet(event, build_plan(event))
    store.update_event(user["id"], event_id, {"run_sheet": sheet})
    return {"run_sheet": sheet}


@router.post("/{event_id}/ideas")
async def generate_ideas(event_id: int, user: dict = Depends(current_user)) -> dict:
    """(Re)generate personalised ideas and cache them on the event."""
    event = _owned(user, event_id)
    ideas = await ai.generate_ideas(event, build_plan(event))
    store.update_event(user["id"], event_id, {"ideas": ideas})
    return {"ideas": ideas}


@router.post("/{event_id}/invite")
async def generate_invite(
    event_id: int, payload: InviteRequest, user: dict = Depends(current_user)
) -> dict:
    """Three creative invite concepts (copy + design brief); cached on the event."""
    event = _owned(user, event_id)
    invite = await ai.generate_invite(event, payload.model_dump())  # details may gain brief facts
    store.update_event(user["id"], event_id, {"invite": invite})
    store.clear_art(event_id)  # artwork belonged to the previous concepts
    return {"invite": invite, "art": []}


@router.get("/{event_id}/invite/art")
async def list_art(event_id: int, user: dict = Depends(current_user)) -> dict:
    _owned(user, event_id)
    return {"art": store.art_keys(event_id)}


@router.post("/{event_id}/invite/art")
async def paint_art(
    event_id: int, payload: ArtRequest, user: dict = Depends(current_user)
) -> dict:
    """Paint a background for one concept and format with Gemini's image model."""
    event = _owned(user, event_id)
    concepts = (event.get("invite") or {}).get("concepts") or []
    if payload.concept >= len(concepts):
        raise HTTPException(status_code=404, detail="create invite concepts first")
    aspect = "4:5" if payload.format == "invite" else "21:9"
    try:
        mime, data = await generate_image(
            ai.art_prompt(concepts[payload.concept], payload.format, event), aspect
        )
    except LLMUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="AI artwork needs Gemini; try again in a moment"
        ) from exc
    key = f"{payload.concept}-{payload.format}"
    store.save_art(event_id, key, mime, data)
    return {"key": key}


@router.get("/{event_id}/invite/art/{key}")
async def get_art(event_id: int, key: str, user: dict = Depends(current_user)) -> Response:
    _owned(user, event_id)
    art = store.get_art(event_id, key)
    if art is None:
        raise HTTPException(status_code=404, detail="no artwork yet")
    mime, data = art
    return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})


@router.post("/{event_id}/ask")
async def ask(event_id: int, payload: AskRequest, user: dict = Depends(current_user)) -> dict:
    event = _owned(user, event_id)
    history = [turn.model_dump() for turn in payload.history]
    return await ai.answer(event, build_plan(event), payload.question, history)


@router.get("/{event_id}/calendar.ics")
async def calendar(event_id: int, user: dict = Depends(current_user)) -> Response:
    event = _owned(user, event_id)
    return Response(
        to_ics(event, build_plan(event)),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="utsav-{event_id}.ics"'},
    )


@notifications_router.get("")
async def notifications(user: dict = Depends(current_user)) -> dict:
    """Alerts across all of the user's events, most urgent first."""
    items = []
    for event in store.list_events(user["id"]):
        items += build_notifications(event, build_plan(event))
    items.sort(key=urgency)
    return {"notifications": items}
