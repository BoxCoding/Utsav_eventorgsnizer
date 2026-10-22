"""Runtime settings, read once from the environment (and a local .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

_ON_VERCEL = bool(os.getenv("VERCEL"))


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-3.1-flash-lite"))
    offline: bool = field(default_factory=lambda: _env("UTSAV_OFFLINE") == "1")
    # Serverless filesystems are read-only except /tmp.
    db_path: str = field(
        default_factory=lambda: _env(
            "UTSAV_DB", "/tmp/utsav.db" if _ON_VERCEL else str(ROOT / "utsav.db")
        )
    )
    cookie_secure: bool = field(
        default_factory=lambda: _env("UTSAV_COOKIE_SECURE", "1" if _ON_VERCEL else "0") == "1"
    )
    image_model: str = field(
        default_factory=lambda: _env("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
    )
    llm_timeout_seconds: float = 30.0
    image_timeout_seconds: float = 120.0

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key) and not self.offline


settings = Settings()
