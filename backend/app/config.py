"""Runtime settings, read once from the environment (and a local .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    """Runtime settings, read once from the environment."""
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-3.1-flash-lite"))
    offline: bool = field(default_factory=lambda: _env("UTSAV_OFFLINE") == "1")
    db_path: str = field(default_factory=lambda: _env("UTSAV_DB", str(ROOT / "utsav.db")))
    cookie_secure: bool = field(
        default_factory=lambda: _env("UTSAV_COOKIE_SECURE", "0") == "1"  # the Dockerfile sets 1
    )
    image_model: str = field(
        default_factory=lambda: _env("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
    )
    # "sqlite" (local/dev/tests) or "firestore" (production: survives redeploys and scales)
    store: str = field(default_factory=lambda: _env("UTSAV_STORE", "sqlite"))
    # WhatsApp Business Cloud API; empty token = "not connected" (one-tap links only)
    whatsapp_token: str = field(default_factory=lambda: _env("WHATSAPP_TOKEN"))
    whatsapp_phone_id: str = field(default_factory=lambda: _env("WHATSAPP_PHONE_NUMBER_ID"))
    whatsapp_app_secret: str = field(default_factory=lambda: _env("WHATSAPP_APP_SECRET"))
    whatsapp_verify_token: str = field(default_factory=lambda: _env("WHATSAPP_VERIFY_TOKEN"))
    whatsapp_invite_template: str = field(
        default_factory=lambda: _env("WHATSAPP_INVITE_TEMPLATE", "utsav_invite"))
    whatsapp_reminder_template: str = field(
        default_factory=lambda: _env("WHATSAPP_REMINDER_TEMPLATE", "utsav_reminder"))
    whatsapp_lang: str = field(default_factory=lambda: _env("WHATSAPP_TEMPLATE_LANG", "en"))
    whatsapp_api_version: str = field(default_factory=lambda: _env("WHATSAPP_API_VERSION", "v21.0"))
    # Origins of the bundled native apps (Capacitor Android / iOS) allowed to call the API
    app_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip() for o in _env("UTSAV_APP_ORIGINS", "https://localhost,capacitor://localhost")
        .split(",") if o.strip()))
    llm_timeout_seconds: float = 30.0
    image_timeout_seconds: float = 120.0

    @property
    def llm_enabled(self) -> bool:
        """True when a Gemini key is set and offline mode is off."""
        return bool(self.gemini_api_key) and not self.offline


settings = Settings()
