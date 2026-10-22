"""Thin async client for the Gemini REST API.

Design goals:
  * The API key lives only in this process (sent via header, never in URLs,
    never logged, never exposed to the frontend).
  * Every caller must handle `LLMUnavailableError` — the app degrades to
    deterministic fallback content instead of breaking the planner's flow.
  * JSON responses are requested via `responseMimeType` and validated by the
    caller, so a malformed generation can never corrupt state.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger("utsav.gemini")

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class LLMUnavailableError(Exception):
    """Raised when Gemini cannot be reached or returns an unusable response."""


async def generate_text(
    prompt: str,
    system: str | None = None,
    history: list[dict[str, Any]] | None = None,
    temperature: float | None = None,
) -> str:
    """Generate free-form text (markdown) from Gemini.

    `history` replays earlier conversation turns ({"role": "user"|"model",
    "content": str}) so multi-turn chat resolves references to what was
    already said.
    """
    return await _generate(
        prompt, system=system, json_mode=False, history=history, temperature=temperature
    )


async def generate_json(
    prompt: str,
    system: str | None = None,
    image_base64: str | None = None,
    image_mime: str = "image/jpeg",
) -> Any:
    """Generate and parse a JSON payload from Gemini (optionally multimodal)."""
    raw = await _generate(
        prompt, system=system, json_mode=True,
        image_base64=image_base64, image_mime=image_mime,
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Gemini returned non-JSON payload: %s", exc)
        raise LLMUnavailableError("model returned malformed JSON") from exc


async def _generate(
    prompt: str,
    system: str | None,
    json_mode: bool,
    image_base64: str | None = None,
    image_mime: str = "image/jpeg",
    history: list[dict[str, Any]] | None = None,
    temperature: float | None = None,
) -> str:
    if not settings.llm_enabled:
        raise LLMUnavailableError("no API key configured or offline mode active")

    parts: list[dict[str, Any]] = [{"text": prompt}]
    if image_base64:
        parts.append({"inline_data": {"mime_type": image_mime, "data": image_base64}})

    contents: list[dict[str, Any]] = [
        {
            "role": turn["role"] if turn.get("role") == "model" else "user",
            "parts": [{"text": str(turn.get("content", ""))}],
        }
        for turn in (history or [])
        if str(turn.get("content", "")).strip()
    ]
    contents.append({"role": "user", "parts": parts})

    body: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.6 if temperature is None else temperature,
            "maxOutputTokens": 4096,
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    url = f"{_BASE_URL}/{settings.gemini_model}:generateContent"
    headers = {"x-goog-api-key": settings.gemini_api_key}

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("Gemini request failed: %s", type(exc).__name__)
        raise LLMUnavailableError("network error talking to Gemini") from exc

    if response.status_code != 200:
        logger.warning("Gemini returned HTTP %s", response.status_code)
        raise LLMUnavailableError(f"Gemini HTTP {response.status_code}")

    try:
        payload = response.json()
        parts = payload["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts).strip()
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMUnavailableError("unexpected Gemini response shape") from exc

    if not text:
        raise LLMUnavailableError("empty Gemini response")
    return text


_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


async def generate_image(prompt: str, aspect_ratio: str) -> tuple[str, bytes]:
    """Generate one image; returns (mime type, bytes). Raises LLMUnavailableError on any failure."""
    if not settings.llm_enabled:
        raise LLMUnavailableError("no API key configured or offline mode active")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": aspect_ratio},
        },
    }
    url = f"{_BASE_URL}/{settings.image_model}:generateContent"
    try:
        async with httpx.AsyncClient(timeout=settings.image_timeout_seconds) as client:
            response = await client.post(
                url, json=body, headers={"x-goog-api-key": settings.gemini_api_key}
            )
    except httpx.HTTPError as exc:
        logger.warning("Gemini image request failed: %s", type(exc).__name__)
        raise LLMUnavailableError("network error talking to Gemini") from exc
    if response.status_code != 200:
        logger.warning("Gemini image returned HTTP %s", response.status_code)
        raise LLMUnavailableError(f"Gemini HTTP {response.status_code}")
    try:
        parts = response.json()["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMUnavailableError("unexpected Gemini image response shape") from exc
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("mimeType", inline.get("mime_type")) in _IMAGE_MIMES:
            data = base64.b64decode(inline["data"])
            if len(data) > MAX_IMAGE_BYTES:
                raise LLMUnavailableError("generated image too large")
            return inline.get("mimeType", inline.get("mime_type")), data
    raise LLMUnavailableError("Gemini returned no image")
