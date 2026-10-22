"""WhatsApp Business Cloud API (Meta Graph) for bulk invites and host reminders.

Business-initiated messages must use templates approved in WhatsApp Manager, so Utsav
sends two (names configurable; text in README):
  * invite   - image header (the AI poster/card) + body {{1}} guest, {{2}} event,
               {{3}} date, {{4}} the concept's message
  * reminder - body {{1}} event, {{2}} the alert
Without credentials everything reports "not connected" and the app keeps its one-tap
wa.me links. The token is only sent as a bearer header and never logged.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger("utsav.whatsapp")
_GRAPH = "https://graph.facebook.com"
CONCURRENCY = 8


class WhatsAppError(Exception):
    """Raised when WhatsApp isn't configured or the Graph API rejects a call."""


def configured() -> bool:
    return bool(settings.whatsapp_token and settings.whatsapp_phone_id)


def _url(path: str) -> str:
    return f"{_GRAPH}/{settings.whatsapp_api_version}/{settings.whatsapp_phone_id}/{path}"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.whatsapp_token}"}


def to_msisdn(phone: str, country_code: str) -> str:
    """E.164 digits without '+': a local number gets the default country code."""
    digits = re.sub(r"\D", "", phone)
    if phone.strip().startswith("+"):
        return digits
    return re.sub(r"\D", "", country_code) + digits.lstrip("0")


def param(text: str) -> str:
    """Template parameters may not contain newlines, tabs or 4+ consecutive spaces."""
    return re.sub(r"\s+", " ", text).strip()[:1000] or "-"


async def _post(client: httpx.AsyncClient, path: str, **kwargs: Any) -> dict[str, Any]:
    if not configured():
        raise WhatsAppError("WhatsApp Business isn't connected")
    try:
        response = await client.post(_url(path), headers=_headers(), **kwargs)
    except httpx.HTTPError as exc:
        raise WhatsAppError("network error talking to WhatsApp") from exc
    body = response.json() if response.content else {}
    if response.status_code != 200:
        message = (body.get("error") or {}).get("message", f"HTTP {response.status_code}")
        logger.warning("WhatsApp API error: %s", message)
        raise WhatsAppError(message[:200])
    return body


async def upload_media(client: httpx.AsyncClient, data: bytes, mime: str) -> str:
    body = await _post(client, "media", data={"messaging_product": "whatsapp", "type": mime},
                       files={"file": ("invite", data, mime)})
    return str(body["id"])


async def send_template(
    client: httpx.AsyncClient, to: str, template: str, params: list[str],
    image_id: str | None = None,
) -> str:
    components: list[dict[str, Any]] = []
    if image_id:
        components.append({"type": "header",
                           "parameters": [{"type": "image", "image": {"id": image_id}}]})
    components.append({"type": "body",
                       "parameters": [{"type": "text", "text": param(p)} for p in params]})
    body = await _post(client, "messages", json={
        "messaging_product": "whatsapp", "to": to, "type": "template",
        "template": {"name": template, "language": {"code": settings.whatsapp_lang},
                     "components": components},
    })
    return str(body["messages"][0]["id"])


async def send_bulk(
    recipients: list[tuple[str, list[str]]], template: str, image: tuple[str, bytes] | None,
) -> list[dict[str, str]]:
    """Send one template per (msisdn, params); returns {"id"} or {"error"} per recipient."""
    sem = asyncio.Semaphore(CONCURRENCY)  # stays well under Cloud API throughput limits
    async with httpx.AsyncClient(timeout=30) as client:
        image_id = await upload_media(client, image[1], image[0]) if image else None

        async def one(to: str, params: list[str]) -> dict[str, str]:
            async with sem:
                try:
                    return {"id": await send_template(client, to, template, params, image_id)}
                except WhatsAppError as exc:
                    return {"error": str(exc)}

        return await asyncio.gather(*(one(to, p) for to, p in recipients))


def valid_signature(raw: bytes, header: str) -> bool:
    """Meta signs webhook bodies with the app secret (X-Hub-Signature-256)."""
    if not settings.whatsapp_app_secret or not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.whatsapp_app_secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def statuses(payload: Any) -> list[tuple[str, str]]:
    """(message id, status) pairs from a webhook payload; anything malformed is skipped."""
    out = []
    for entry in payload.get("entry", []) if isinstance(payload, dict) else []:
        for change in entry.get("changes", []) if isinstance(entry, dict) else []:
            value = change.get("value") if isinstance(change, dict) else None
            for st in (value or {}).get("statuses", []) if isinstance(value, dict) else []:
                if isinstance(st, dict) and st.get("status") in STATUS_RANK:
                    out.append((str(st.get("id", "")), st["status"]))
    return out


# Webhooks can arrive out of order: never move a guest backwards (read -> delivered).
STATUS_RANK = {"sent": 1, "delivered": 2, "read": 3, "failed": 4}
