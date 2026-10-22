import base64
import json

import httpx
import pytest
from backend.app import gemini_client
from backend.app.config import settings
from backend.app.gemini_client import LLMUnavailableError

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def gemini(monkeypatch):
    """Gemini enabled against a fake endpoint; `reply` sets what the next call returns."""
    object.__setattr__(settings, "gemini_api_key", "test-key")
    object.__setattr__(settings, "offline", False)
    state = {"reply": httpx.Response(200, json={}), "requests": []}

    def handler(request):
        state["requests"].append(request)
        reply = state["reply"]
        return reply(request) if callable(reply) else reply

    real = httpx.AsyncClient
    monkeypatch.setattr(gemini_client.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    yield state
    object.__setattr__(settings, "gemini_api_key", "")
    object.__setattr__(settings, "offline", True)


def text_reply(text):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


async def test_text_sends_key_in_header_never_in_url(gemini):
    gemini["reply"] = text_reply("Book the venue first.")
    out = await gemini_client.generate_text("What first?", system="Be brief",
                                            history=[{"role": "model", "content": "Hi"}])
    assert out == "Book the venue first."
    req = gemini["requests"][0]
    assert req.headers["x-goog-api-key"] == "test-key" and "test-key" not in str(req.url)
    body = json.loads(req.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "Be brief"
    assert [c["role"] for c in body["contents"]] == ["model", "user"]


async def test_json_mode_parses_and_rejects_malformed(gemini):
    gemini["reply"] = text_reply('{"ok": true}')
    assert await gemini_client.generate_json("x", image_base64="aGk=") == {"ok": True}
    body = json.loads(gemini["requests"][0].content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["contents"][0]["parts"][1]["inline_data"]["data"] == "aGk="
    gemini["reply"] = text_reply("not json")
    with pytest.raises(LLMUnavailableError):
        await gemini_client.generate_json("x")


@pytest.mark.parametrize("reply", [
    httpx.Response(429, json={}),
    httpx.Response(200, json={"candidates": []}),
    text_reply("   "),
])
async def test_unusable_responses_raise(gemini, reply):
    gemini["reply"] = reply
    with pytest.raises(LLMUnavailableError):
        await gemini_client.generate_text("x")


async def test_image_returns_bytes_and_enforces_limits(gemini):
    png = b"\x89PNG..."
    part = {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(png).decode()}}
    gemini["reply"] = httpx.Response(200, json={"candidates": [{"content": {"parts": [part]}}]})
    assert await gemini_client.generate_image("a poster", "2:3") == ("image/png", png)
    body = json.loads(gemini["requests"][0].content)
    assert body["generationConfig"]["imageConfig"]["aspectRatio"] == "2:3"
    gemini["reply"] = httpx.Response(200, json={"candidates": [{"content": {"parts": [
        {"inlineData": {"mimeType": "image/svg+xml", "data": "PHN2Zz4="}}]}}]})
    with pytest.raises(LLMUnavailableError):  # only raster formats are accepted
        await gemini_client.generate_image("x", "1:1")


async def test_network_failure_is_unavailable(gemini):
    def boom(request):
        raise httpx.ConnectError("down")

    gemini["reply"] = boom
    with pytest.raises(LLMUnavailableError):
        await gemini_client.generate_text("x")
    with pytest.raises(LLMUnavailableError):
        await gemini_client.generate_image("x", "1:1")
