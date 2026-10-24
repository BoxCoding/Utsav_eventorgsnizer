"""Request models — the trust boundary. Everything from the browser is validated here."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Kind = Literal["wedding", "birthday", "community"]
Currency = Literal[
    "INR", "USD", "EUR", "GBP", "AED", "SAR", "SGD", "AUD", "CAD", "NZD", "JPY", "CHF",
    "ZAR", "NGN", "KES", "BRL", "MXN", "LKR", "NPR", "BDT",
]


class CustomTask(BaseModel):
    title: str = Field(min_length=3, max_length=90)
    category: str = Field(max_length=40)
    lead_days: int = Field(ge=0, le=400)
    vendor: bool = False
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(max_length=254, pattern=EMAIL)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return v.strip().lower()


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)

    @field_validator("email")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return v.strip().lower()


class EventIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Kind
    event_date: date
    guests: int = Field(ge=1, le=10_000)
    budget: int | None = Field(default=None, ge=100, le=10_000_000_000)  # None: Utsav estimates
    budget_note: str = Field(default="", max_length=300)
    currency: Currency = "INR"
    city: str = Field(default="", max_length=80)
    vibe: str = Field(default="", max_length=200)
    tradition: str = Field(default="", max_length=80)
    brief: str = Field(default="", max_length=3000)
    custom_tasks: list[CustomTask] = Field(default_factory=list, max_length=25)
    split_override: dict[str, float] | None = Field(default=None, max_length=16)
    skipped: list[str] = Field(default_factory=list, max_length=40)

    @field_validator("event_date")
    @classmethod
    def _not_past(cls, v: date) -> date:
        if v < date.today():
            raise ValueError("event date can't be in the past")
        return v


class Guest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # "   " is not a name

    name: str = Field(min_length=1, max_length=80)
    email: str = Field(default="", max_length=254, pattern=r"^$|" + EMAIL)
    phone: str = Field(default="", max_length=24, pattern=r"^$|^\+?[0-9 ()-]{6,24}$")
    sent_wa: bool = False
    sent_email: bool = False
    wa_id: str = Field(default="", max_length=200)  # Cloud API message id, for delivery status
    wa_status: Literal["", "sent", "delivered", "read", "failed"] = ""


class EventPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    event_date: date | None = None
    guests: int | None = Field(default=None, ge=1, le=10_000)
    budget: int | None = Field(default=None, ge=100, le=10_000_000_000)
    currency: Currency | None = None
    city: str | None = Field(default=None, max_length=80)
    vibe: str | None = Field(default=None, max_length=200)
    tradition: str | None = Field(default=None, max_length=80)
    done: list[str] | None = Field(default=None, max_length=100)
    spend: dict[str, int] | None = Field(default=None, max_length=30)
    guest_list: list[Guest] | None = Field(default=None, max_length=500)
    brief: str | None = Field(default=None, max_length=3000)
    custom_tasks: list[CustomTask] | None = Field(default=None, max_length=25)
    split_override: dict[str, float] | None = Field(default=None, max_length=16)
    skipped: list[str] | None = Field(default=None, max_length=40)

    @field_validator("spend")
    @classmethod
    def _non_negative(cls, v: dict[str, int] | None) -> dict[str, int] | None:
        if v is not None and any(amount < 0 or amount > 1_000_000_000 for amount in v.values()):
            raise ValueError("spend amounts must be between 0 and 1,000,000,000")
        return v

    @field_validator("event_date")
    @classmethod
    def _not_past(cls, v: date | None) -> date | None:
        if v is not None and v < date.today():
            raise ValueError("event date can't be in the past")
        return v


class InviteRequest(BaseModel):
    tone: Literal["elegant", "fun", "formal", "minimal"] = "elegant"
    host: str = Field(default="", max_length=100)
    venue: str = Field(default="", max_length=150)
    time: str = Field(default="", max_length=60)
    rsvp: str = Field(default="", max_length=150)


class BriefRequest(BaseModel):
    brief: str = Field(min_length=15, max_length=3000)
    kind: Kind | None = None  # set when re-planning an existing event (its type is fixed)


class ArtRequest(BaseModel):
    concept: int = Field(ge=0, le=2)
    format: Literal["invite", "banner", "poster"]


class Turn(BaseModel):
    role: Literal["user", "model"]
    content: str = Field(max_length=2000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    history: list[Turn] = Field(default_factory=list, max_length=6)


COUNTRY_CODE = Field(default="+91", pattern=r"^\+?[0-9]{1,4}$")


class WaInviteRequest(BaseModel):
    message: str = Field(min_length=1, max_length=900)  # concept text; {name} = first name
    country_code: str = COUNTRY_CODE
    only_unsent: bool = True
    # The image header: the stored AI poster, or the card the browser composed (PNG, base64)
    image: Literal["poster", "card"] = "poster"
    card_png: str = Field(default="", max_length=8_000_000)
    concept: int = Field(default=0, ge=0, le=2)


class WaRemindRequest(BaseModel):
    phone: str = Field(pattern=r"^\+?[0-9 ()-]{6,24}$")
    country_code: str = COUNTRY_CODE
