"""GenAI layer: personalised ideas, invitations, brief reading, run sheets, reminders and a
plan-grounded assistant.

The model receives the deterministic plan as context and is told to quote figures only
from it. User-supplied text is passed as delimited data, never as instructions. When
Gemini is unavailable, deterministic fallbacks answer from the same plan, so the app
always responds. Routes use `ai.<name>`; tests patch `ai.gemini_client` and
`ai.proofread_poster` here.
"""
from .. import gemini_client
from ..gemini_client import LLMUnavailableError
from .assistant import answer, fallback_answer
from .brief import _clean_brief, current_plan, fallback_brief, read_brief
from .common import pretty_date
from .ideas import _clean_ideas, fallback_ideas, generate_ideas
from .invites import (
    COPY_LIMITS,
    _clean_concept,
    _clean_invite,
    _merge_details,
    art_prompt,
    fallback_invite,
    generate_invite,
    poster_lines,
    poster_prompt,
    proofread_poster,
)
from .schedule import _clean_run_sheet, generate_brief_alerts, generate_run_sheet

__all__ = [
    "COPY_LIMITS", "LLMUnavailableError", "_clean_brief", "_clean_concept", "_clean_ideas",
    "_clean_invite", "_clean_run_sheet", "_merge_details", "answer", "art_prompt",
    "current_plan", "fallback_answer", "fallback_brief", "fallback_ideas", "fallback_invite",
    "gemini_client", "generate_brief_alerts", "generate_ideas", "generate_invite",
    "generate_run_sheet", "poster_lines", "poster_prompt", "pretty_date", "proofread_poster",
    "read_brief",
]
