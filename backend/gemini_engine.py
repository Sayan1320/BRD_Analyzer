"""
gemini_engine.py — Gemini AI analysis for the Requirement Summarizer.

Sends extracted text to gemini-2.0-flash with a structured prompt and parses
the JSON response into an AnalysisResult. On any JSON parse failure, returns a
safe fallback with the raw text in executive_summary and empty lists.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import google.api_core.exceptions as gcp_exc
from google import genai
from google.genai import types as _genai_types
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from logging_config import get_logger

# ---------------------------------------------------------------------------
# Module-level Gemini client (initialized once at import time)
# ---------------------------------------------------------------------------
_API_KEY = os.environ.get("GOOGLE_AI_API_KEY", "")
_client = genai.Client(api_key=_API_KEY if _API_KEY else "placeholder")
_MODEL_NAME = "gemini-2.0-flash"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class UserStory:
    id: str
    role: str
    feature: str
    benefit: str
    priority: str


@dataclass
class AnalysisResult:
    executive_summary: str
    user_stories: list[UserStory] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    gap_flags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """\
You are a requirements analyst. Analyze the following requirements document and \
return a JSON object with EXACTLY these four keys:

- "executive_summary": a concise high-level summary (string)
- "user_stories": a list of objects, each with exactly the keys \
"id", "role", "feature", "benefit", "priority" (all strings)
- "acceptance_criteria": a list of acceptance criteria strings
- "gap_flags": a list of strings describing gaps or missing requirements

Respond with ONLY valid JSON — no markdown, no code fences, no extra text.

Document:
{text}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|```$", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) from a string."""
    return _CODE_FENCE_RE.sub("", text).strip()


def _parse_user_story(raw: dict) -> UserStory:
    return UserStory(
        id=str(raw.get("id", "")),
        role=str(raw.get("role", "")),
        feature=str(raw.get("feature", "")),
        benefit=str(raw.get("benefit", "")),
        priority=str(raw.get("priority", "")),
    )


# ---------------------------------------------------------------------------
# Tenacity retry helpers
# ---------------------------------------------------------------------------


def _log_retry(retry_state):
    log = get_logger("gemini_engine")
    log.warning(
        "gemini_retry",
        attempt_number=retry_state.attempt_number,
        wait_seconds=retry_state.next_action.sleep if retry_state.next_action else 0,
        error_type=type(retry_state.outcome.exception()).__name__ if retry_state.outcome else "unknown",
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=2, max=10),
    retry=retry_if_exception_type((
        gcp_exc.ServiceUnavailable,
        gcp_exc.DeadlineExceeded,
        gcp_exc.ResourceExhausted,
    )),
    reraise=True,
    before_sleep=_log_retry,
)
async def _call_gemini(prompt: str) -> str:
    response = await _client.aio.models.generate_content(
        model=_MODEL_NAME,
        contents=prompt,
    )
    return response.text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def analyze(text: str) -> AnalysisResult:
    """
    Call gemini-2.0-flash with a structured prompt and return an AnalysisResult.

    If the response cannot be parsed as JSON, returns a fallback AnalysisResult
    with the raw response text in executive_summary and empty lists.
    """
    log = get_logger("gemini_engine")

    # Token budget guard (Req 9.6)
    if len(text) > 100_000:
        log.warning("text_truncated", original_chars=len(text), truncated_to=100_000)
        text = text[:100_000]

    prompt = _PROMPT_TEMPLATE.format(text=text)

    raw_text: str = await _call_gemini(prompt)

    # Token usage warning (placeholder — tokens not tracked yet)
    tokens_used = 0
    if tokens_used > 8000:
        log.warning("high_token_usage", tokens_used=tokens_used)

    cleaned = _strip_code_fences(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return AnalysisResult(
            executive_summary=raw_text,
            user_stories=[],
            acceptance_criteria=[],
            gap_flags=[],
        )

    user_stories = [
        _parse_user_story(us)
        for us in data.get("user_stories", [])
        if isinstance(us, dict)
    ]

    return AnalysisResult(
        executive_summary=str(data.get("executive_summary", "")),
        user_stories=user_stories,
        acceptance_criteria=[str(c) for c in data.get("acceptance_criteria", [])],
        gap_flags=[str(g) for g in data.get("gap_flags", [])],
    )
