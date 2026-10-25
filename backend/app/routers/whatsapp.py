"""WhatsApp Business Cloud API: bulk invites, host reminders and delivery receipts.

Returns 503 until credentials are set; the UI then keeps wa.me links.
"""
from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from .. import store, whatsapp
from ..ai import pretty_date
from ..auth import current_user
from ..config import settings
from ..limits import WHATSAPP
from ..notify import build_notifications, urgency
from ..planner import build_plan
from ..schemas import WaInviteRequest, WaRemindRequest
from .events import _owned

router = APIRouter(prefix="/api", tags=["whatsapp"])
MAX_BULK = 250


def _require_connected() -> None:
    if not whatsapp.configured():
        raise HTTPException(
            status_code=503,
            detail="WhatsApp Business isn't connected yet; use the one-tap WhatsApp links.",
        )


@router.get("/whatsapp/status")
async def status() -> dict:
    """Whether WhatsApp Business is connected on this server."""
    return {"connected": whatsapp.configured()}


def _invite_image(event_id: int, payload: WaInviteRequest) -> tuple[str, bytes]:
    if payload.image == "poster":
        art = store.get_art(event_id, f"{payload.concept}-poster")
        if art is None:
            raise HTTPException(status_code=404, detail="paint the AI poster first")
        return art
    try:
        data = base64.b64decode(payload.card_png, validate=True)
    except binascii.Error as exc:
        raise HTTPException(status_code=422, detail="card image is not valid base64") from exc
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=422, detail="card image must be a PNG")
    return "image/png", data


@router.post("/events/{event_id}/whatsapp/invite", dependencies=[WHATSAPP])
async def send_invites(
    event_id: int, payload: WaInviteRequest, user: dict = Depends(current_user)
) -> dict:
    """Send the invite template, with the design as its image, to every guest with a phone."""
    _require_connected()
    event = _owned(user, event_id)
    guests = event.get("guest_list") or []
    targets = [i for i, g in enumerate(guests)
               if g.get("phone") and not (payload.only_unsent and g.get("wa_status")
                                          in {"sent", "delivered", "read"})]
    if not targets:
        raise HTTPException(status_code=422, detail="no guests with a phone number left to send")
    if len(targets) > MAX_BULK:
        raise HTTPException(status_code=422, detail=f"send at most {MAX_BULK} at a time")
    image = _invite_image(event_id, payload)
    when = pretty_date(event["event_date"])
    recipients = [
        (whatsapp.to_msisdn(guests[i]["phone"], payload.country_code),
         [event["name"], payload.message.replace("{name}", guests[i]["name"].split()[0]), when])
        for i in targets
    ]
    try:
        results = await whatsapp.send_bulk(recipients, settings.whatsapp_invite_template, image)
    except whatsapp.WhatsAppError as exc:  # media upload failed: nothing was sent
        raise HTTPException(status_code=502, detail=f"WhatsApp: {exc}") from exc
    updated = [dict(g) for g in guests]
    for i, result in zip(targets, results, strict=True):
        ok = "id" in result
        updated[i].update(wa_id=result.get("id", ""), wa_status="sent" if ok else "failed",
                          sent_wa=updated[i].get("sent_wa") or ok)
    store.update_event(user["id"], event_id, {"guest_list": updated})
    store.record_wa(user["id"], event_id, [r["id"] for r in results if "id" in r])
    errors = list(dict.fromkeys(r["error"] for r in results if "error" in r))
    return {"sent": sum("id" in r for r in results), "failed": sum("error" in r for r in results),
            "errors": errors[:3], "guest_list": updated}


@router.post("/events/{event_id}/whatsapp/remind", dependencies=[WHATSAPP])
async def send_reminder(
    event_id: int, payload: WaRemindRequest, user: dict = Depends(current_user)
) -> dict:
    """Send the host this event's most urgent alerts as one reminder message."""
    _require_connected()
    event = _owned(user, event_id)
    alerts = sorted(build_notifications(event, build_plan(event)), key=urgency)[:5]
    if not alerts:
        raise HTTPException(status_code=422, detail="nothing to remind you about right now")
    summary = " • ".join(f"{a['title']}: {a['message']}" for a in alerts)
    to = whatsapp.to_msisdn(payload.phone, payload.country_code)
    results = await whatsapp.send_bulk(
        [(to, [event["name"], summary])], settings.whatsapp_reminder_template, None)
    if "error" in results[0]:
        raise HTTPException(status_code=502, detail=f"WhatsApp: {results[0]['error']}")
    return {"sent": len(alerts)}


@router.get("/whatsapp/webhook")
async def verify_webhook(
    mode: str = Query("", alias="hub.mode"), token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
) -> Response:
    """Meta's one-time subscription handshake."""
    if (mode == "subscribe" and settings.whatsapp_verify_token
            and token == settings.whatsapp_verify_token):
        return Response(challenge, media_type="text/plain")
    raise HTTPException(status_code=403)


@router.post("/whatsapp/webhook")
async def receive_webhook(request: Request) -> dict:
    """Delivery receipts (sent -> delivered -> read, or failed) update the guest list."""
    raw = await request.body()
    if not whatsapp.valid_signature(raw, request.headers.get("x-hub-signature-256", "")):
        raise HTTPException(status_code=403)
    try:
        payload: Any = json.loads(raw)
    except ValueError:
        return {"ok": True}
    for message_id, new in whatsapp.statuses(payload):
        owner = store.wa_owner(message_id)
        event = store.get_event(*owner) if owner else None
        if owner is None or event is None:
            continue
        guests = event.get("guest_list") or []
        rank = whatsapp.STATUS_RANK
        changed = False
        for g in guests:
            if g.get("wa_id") == message_id and rank[new] > rank.get(g.get("wa_status"), 0):
                g["wa_status"] = new
                changed = True
        if changed:
            store.update_event(owner[0], owner[1], {"guest_list": guests})
    return {"ok": True}
