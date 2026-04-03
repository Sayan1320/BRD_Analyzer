"""
Unit tests for Spec 09 — Rate Limiting and Resilience.

Tests 9.1 through 9.12.
"""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend/ is on the path
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request as StarletteRequest
from ocr_engine import ExtractionResult
from gemini_engine import AnalysisResult
import requirement_summarizer_app as _rs_module
from rate_limiter import limiter


# ---------------------------------------------------------------------------
# One-time setup: wire SlowAPIMiddleware + RateLimitExceeded handler onto rs_app
# so rate limit tests work when testing rs_app directly.
# This mirrors what main.py does for the production app.
# Must be done BEFORE any TestClient is created (before app starts).
# ---------------------------------------------------------------------------

_rs_module.rs_app.state.limiter = limiter
_rs_module.rs_app.add_middleware(SlowAPIMiddleware)


@_rs_module.rs_app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: StarletteRequest, exc: RateLimitExceeded):
    retry_after = int(exc.retry_after) if hasattr(exc, "retry_after") else 60
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": "Rate limit exceeded. Please wait.",
            "retry_after_seconds": retry_after,
        },
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_analyze_patches(
    *,
    db_raises: Exception | None = None,
    db_ok: bool = True,
):
    """
    Return a context manager stack that mocks all /analyze dependencies.
    If db_raises is set, get_session raises that exception.
    If db_ok is True (and db_raises is None), DB succeeds and commits.
    """
    import ocr_engine as _ocr
    import gemini_engine as _gem

    mock_session_record = MagicMock()
    mock_session_record.id = "00000000-0000-0000-0000-000000000001"
    mock_db = AsyncMock()

    analysis_json = json.dumps({
        "executive_summary": "summary",
        "user_stories": [],
        "acceptance_criteria": [],
        "gap_flags": [],
    })

    if db_raises is not None:
        async def _get_session():
            raise db_raises
            yield  # make it an async generator
    else:
        async def _get_session():
            yield mock_db

    return (
        patch("requirement_summarizer_app.get_session", side_effect=_get_session),
        patch("requirement_summarizer_app.create_session_record", new=AsyncMock(return_value=mock_session_record)),
        patch("requirement_summarizer_app.save_document_metadata", new=AsyncMock(return_value=MagicMock(id="doc-1"))),
        patch("requirement_summarizer_app.update_session_extraction", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_result", new=AsyncMock()),
        patch("requirement_summarizer_app.save_analysis_result", new=AsyncMock()),
        patch("requirement_summarizer_app.update_document_status", new=AsyncMock()),
        patch.object(_ocr, "extract_text", return_value=ExtractionResult(text="hello world", char_count=11, page_count=1)),
        patch.object(
            _gem._client.aio.models,
            "generate_content",
            new=AsyncMock(return_value=MagicMock(text=analysis_json)),
        ),
    )


def _txt_file():
    return {"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")}


# ---------------------------------------------------------------------------
# 9.1 — 6th /analyze request from same IP returns 429
# Requirements: 9.1
# ---------------------------------------------------------------------------

def test_rate_limit_analyze_6th_request_returns_429():
    """The 6th /analyze request within a minute from the same IP must return 429."""
    patches = _make_analyze_patches()
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)

        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        limiter.enabled = True
        limiter._storage.reset()
        try:
            for i in range(5):
                resp = client.post("/analyze", files=_txt_file())
                assert resp.status_code == 200, f"Request {i+1} should succeed, got {resp.status_code}"

            resp = client.post("/analyze", files=_txt_file())
            assert resp.status_code == 429
        finally:
            limiter.enabled = False
            limiter._storage.reset()


# ---------------------------------------------------------------------------
# 9.2 — 429 response body has retry_after_seconds key
# Requirements: 9.1, 9.9
# ---------------------------------------------------------------------------

def test_rate_limit_429_body_has_retry_after_seconds():
    """The 429 response body must be valid JSON with error, message, retry_after_seconds."""
    patches = _make_analyze_patches()
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)

        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        limiter.enabled = True
        limiter._storage.reset()
        try:
            for _ in range(5):
                client.post("/analyze", files=_txt_file())

            resp = client.post("/analyze", files=_txt_file())
            assert resp.status_code == 429

            body = resp.json()
            assert "error" in body
            assert "message" in body
            assert "retry_after_seconds" in body
            assert isinstance(body["retry_after_seconds"], int)
        finally:
            limiter.enabled = False
            limiter._storage.reset()


# ---------------------------------------------------------------------------
# 9.3 — Gemini retries on ServiceUnavailable
# Requirements: 9.4
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gemini_retries_on_service_unavailable():
    """A single ServiceUnavailable from Gemini should be retried and succeed."""
    import google.api_core.exceptions as gcp_exc
    import gemini_engine as _gem

    call_count = [0]

    # Patch the inner API call (inside _call_gemini) so tenacity's retry logic fires.
    # _call_gemini is the tenacity-wrapped function; patching _client.aio.models.generate_content
    # means the first call raises ServiceUnavailable and tenacity retries it.
    async def _flaky_generate(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise gcp_exc.ServiceUnavailable("temporary")
        mock_resp = MagicMock()
        mock_resp.text = '{"executive_summary": "ok", "user_stories": [], "acceptance_criteria": [], "gap_flags": []}'
        return mock_resp

    with patch.object(_gem._client.aio.models, "generate_content", side_effect=_flaky_generate):
        result = await _gem.analyze("some text")

    assert result.executive_summary == "ok"
    assert call_count[0] == 2


# ---------------------------------------------------------------------------
# 9.4 — Gemini does NOT retry on ValueError
# Requirements: 9.4
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gemini_does_not_retry_on_value_error():
    """ValueError from Gemini must propagate immediately without retry."""
    import gemini_engine as _gem

    call_count = [0]

    async def _bad_call(prompt):
        call_count[0] += 1
        raise ValueError("bad input")

    with patch.object(_gem, "_call_gemini", side_effect=_bad_call):
        with pytest.raises(ValueError):
            await _gem.analyze("some text")

    assert call_count[0] == 1  # called exactly once, no retry


# ---------------------------------------------------------------------------
# 9.5 — LlamaParse retries exactly once on generic Exception
# Requirements: 9.5
# ---------------------------------------------------------------------------

def test_llamaparse_retries_once_on_exception():
    """LlamaParse load_data should be retried once on a generic Exception."""
    import ocr_engine as _ocr

    call_count = [0]

    def _flaky_load(path, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("network error")
        node = MagicMock()
        node.text = "extracted text"
        return [node]

    mock_parser = MagicMock()
    mock_parser.load_data = _flaky_load

    with patch.object(_ocr, "_llama_parser", mock_parser):
        result = _ocr.extract_text(b"content", "doc.pdf")

    assert call_count[0] == 2
    assert result.text == "extracted text"


# ---------------------------------------------------------------------------
# 9.6 — Text over 100000 chars is truncated before Gemini call
# Requirements: 9.6
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gemini_truncates_text_over_100000_chars():
    """Text longer than 100000 chars must be truncated before the Gemini prompt."""
    import gemini_engine as _gem

    long_text = "x" * 150_000
    captured_prompt = []

    async def _capture_call(prompt):
        captured_prompt.append(prompt)
        return '{"executive_summary": "ok", "user_stories": [], "acceptance_criteria": [], "gap_flags": []}'

    with patch.object(_gem, "_call_gemini", side_effect=_capture_call):
        await _gem.analyze(long_text)

    assert len(captured_prompt) == 1
    # The 150000 x's should have been truncated — 100001 consecutive x's must not appear
    assert "x" * 100_001 not in captured_prompt[0]


# ---------------------------------------------------------------------------
# 9.7 — /analyze returns db_persisted=False when DB raises
# Requirements: 9.7
# ---------------------------------------------------------------------------

def test_analyze_returns_result_with_db_persisted_false_when_db_raises():
    """When DB raises, /analyze must still return HTTP 200 with db_persisted=False."""
    from database import DatabaseError

    patches = _make_analyze_patches(db_raises=DatabaseError("connection failed"))
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        resp = client.post("/analyze", files=_txt_file())

    assert resp.status_code == 200
    body = resp.json()
    assert body["db_persisted"] is False
    assert "analysis" in body


# ---------------------------------------------------------------------------
# 9.8 — /analyze returns db_persisted=True on successful DB write
# Requirements: 9.7
# ---------------------------------------------------------------------------

def test_analyze_returns_db_persisted_true_on_successful_db_write():
    """When DB succeeds, /analyze must return HTTP 200 with db_persisted=True."""
    patches = _make_analyze_patches(db_ok=True)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        resp = client.post("/analyze", files=_txt_file())

    assert resp.status_code == 200
    body = resp.json()
    assert body["db_persisted"] is True
    assert "analysis" in body


# ---------------------------------------------------------------------------
# 9.9 — /health response contains components dict with all three keys
# Requirements: 9.8
# ---------------------------------------------------------------------------

def test_health_response_contains_components_with_three_keys():
    """GET /health must return a components dict with database, gemini_api, llamaparse_api."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    async def _ok_get_session():
        yield mock_db

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_ok_get_session),
        patch("os.getenv", side_effect=lambda k, *a: "dummy" if k in ("GOOGLE_AI_API_KEY", "LLAMA_CLOUD_API_KEY") else os.environ.get(k, *a)),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert "components" in body
    components = body["components"]
    assert "database" in components
    assert "gemini_api" in components
    assert "llamaparse_api" in components


# ---------------------------------------------------------------------------
# 9.10 — /health status is "degraded" when DB is unreachable
# Requirements: 9.8
# ---------------------------------------------------------------------------

def test_health_status_degraded_when_db_unreachable():
    """When DB raises, /health must return status='degraded'."""
    async def _failing_get_session():
        raise Exception("DB unreachable")
        yield  # make it an async generator

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_failing_get_session),
        patch("os.getenv", side_effect=lambda k, *a: "dummy" if k in ("GOOGLE_AI_API_KEY", "LLAMA_CLOUD_API_KEY") else os.environ.get(k, *a)),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["components"]["database"] == "error"


# ---------------------------------------------------------------------------
# 9.11 — /health still returns HTTP 200 even when status is "degraded"
# Requirements: 9.8
# ---------------------------------------------------------------------------

def test_health_returns_200_even_when_degraded():
    """Even when DB is down, /health must return HTTP 200 (not 503)."""
    async def _failing_get_session():
        raise Exception("DB unreachable")
        yield  # make it an async generator

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_failing_get_session),
        patch("os.getenv", side_effect=lambda k, *a: None if k in ("GOOGLE_AI_API_KEY", "LLAMA_CLOUD_API_KEY") else os.environ.get(k, *a)),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        resp = client.get("/health")

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 9.12 — /voice-story rate limit is 10/minute not 5/minute
# Requirements: 9.2
# ---------------------------------------------------------------------------

def test_voice_story_rate_limit_is_10_per_minute():
    """
    /voice-story must allow 10 requests per minute.
    The 6th request must NOT return 429 (it's 10/min, not 5/min).
    The 11th request must return 429.
    """
    import voice_engine as _ve

    fake_wav = b"RIFF" + b"\x00" * 36

    with (
        patch.object(_ve, "format_story_narration", return_value="As a user, I want to test."),
        patch.object(_ve, "text_to_speech_custom", new=AsyncMock(return_value=fake_wav)),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)

        limiter.enabled = True
        limiter._storage.reset()
        try:
            story_payload = {
                "story": {
                    "id": "US-1",
                    "role": "user",
                    "feature": "test",
                    "benefit": "coverage",
                    "priority": "high",
                },
                "voice": "Aoede",
            }

            # Requests 1-10 should all succeed
            for i in range(10):
                resp = client.post("/voice-story", json=story_payload)
                assert resp.status_code == 200, f"Request {i+1} should succeed, got {resp.status_code}"

            # 11th request should be rate-limited
            resp = client.post("/voice-story", json=story_payload)
            assert resp.status_code == 429
        finally:
            limiter.enabled = False
            limiter._storage.reset()
