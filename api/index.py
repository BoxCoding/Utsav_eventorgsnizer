"""Vercel serverless entry point.

Vercel's Python runtime serves the ASGI `app` exported here. All /api/*
requests are routed to this function (see ../vercel.json); static frontend
files are served from Vercel's CDN, same-origin — so cookies stay first-party
and no CORS is involved.

The project root is put on sys.path explicitly: the function is executed from
its own directory, so `backend` would otherwise not be importable.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.main import app  # noqa: E402  (path setup must precede this import)

__all__ = ["app"]
