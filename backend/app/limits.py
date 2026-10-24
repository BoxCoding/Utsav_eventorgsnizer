"""Per-user quotas on the routes that cost money (Gemini text/image calls, WhatsApp sends),
so one account or a stolen session can't run up the bill or spam guests."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Depends, HTTPException

from .auth import current_user, prune_window

# shortcut: per-process memory, like the login limiter; move to Redis/Firestore past 1 instance.
_hits: dict[tuple[str, int], deque[float]] = defaultdict(deque)


def quota(bucket: str, limit: int, window: float) -> Callable:
    """Dependency: at most `limit` calls per `window` seconds per user for this bucket."""

    async def check(user: dict = Depends(current_user)) -> None:
        now = time.monotonic()
        hits = _hits[(bucket, user["id"])]
        prune_window(hits, window, now)
        if len(hits) >= limit:
            wait = int(window - (now - hits[0])) + 1
            raise HTTPException(status_code=429, detail=f"Too many requests; try again in {wait}s",
                                headers={"Retry-After": str(wait)})
        hits.append(now)

    return check


AI_TEXT = Depends(quota("ai", 40, 600))      # ideas, invites, ask, brief, re-plan, run sheet…
AI_IMAGE = Depends(quota("image", 15, 600))  # each poster may take 3 image calls
WHATSAPP = Depends(quota("whatsapp", 10, 600))
