"""
Unit tests for the demo endpoints — Spec 10, Task 15.

Covers:
  15.1 — GET /demo/sample-text returns text, filename, file_type keys
  15.2 — POST /demo/analyze returns response with all required fields
  15.3 — POST /demo/analyze response shape matches /analyze schema
  15.4 — POST /demo/analyze makes no calls to gemini_engine or ocr_engine
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure backend/ is on the path
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from fastapi.testclient import TestClient
import requirement_summarizer_app as _rs_module


# ---------------------------------------------------------------------------
# Helper — build a TestClient with DB mocked so the app starts cleanly.
# The demo endpoints don't touch OCR or Gemini, but the app still needs
# get_session available for other routes that share the same app instance.
# ---------------------------------------------------------------------------

def _make_demo_client() -> TestClient:
    """Return a synchronous TestClient with only the DB session mocked."""
    mock_db = AsyncMock()

    async def _ok_get_session():
        yield mock_db

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_ok_get_session),
        patch("requirement_summarizer_app.validate_env_vars"),
        patch("database.init_db", new=AsyncMock()),
    ):
        return TestClient(_rs_module.rs_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 15.1 — GET /demo/sample-text returns text, filename, file_type keys
# Requirements: 10.2
# ---------------------------------------------------------------------------

def test_sample_text_status_200():
    """GET /demo/sample-text must return HTTP 200."""
    client = _make_demo_client()
    response = client.get("/demo/sample-text")
    assert response.status_code == 200


def test_sample_text_has_required_keys():
    """GET /demo/sample-text response must contain text, filename, file_type."""
    client = _make_demo_client()
    body = client.get("/demo/sample-text").json()
    assert "text" in body
    assert "filename" in body
    assert "file_type" in body


def test_sample_text_filename_and_file_type():
    """GET /demo/sample-text must return filename='sample_brd.txt' and file_type='txt'."""
    client = _make_demo_client()
    body = client.get("/demo/sample-text").json()
    assert body["filename"] == "sample_brd.txt"
    assert body["file_type"] == "txt"


def test_sample_text_is_non_empty_string():
    """GET /demo/sample-text must return a non-empty string for 'text'."""
    client = _make_demo_client()
    body = client.get("/demo/sample-text").json()
    assert isinstance(body["text"], str)
    assert len(body["text"]) > 0


# ---------------------------------------------------------------------------
# 15.2 — POST /demo/analyze returns response with all required fields
# Requirements: 10.3, 10.4
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = [
    "executive_summary",
    "user_stories",
    "acceptance_criteria",
    "gap_flags",
    "tokens_used",
    "processing_time_ms",
    "model_used",
    "document_id",
    "session_id",
    "db_persisted",
    "request_id",
]


def test_demo_analyze_status_200():
    """POST /demo/analyze must return HTTP 200."""
    client = _make_demo_client()
    response = client.post("/demo/analyze")
    assert response.status_code == 200


def test_demo_analyze_has_all_required_fields():
    """POST /demo/analyze must include all required top-level fields."""
    client = _make_demo_client()
    body = client.post("/demo/analyze").json()
    for field in _REQUIRED_FIELDS:
        assert field in body, f"Missing required field: {field}"


# ---------------------------------------------------------------------------
# 15.3 — POST /demo/analyze response shape matches /analyze schema
# Requirements: 10.3
# ---------------------------------------------------------------------------

def test_demo_analyze_user_stories_is_list():
    """user_stories must be a list."""
    client = _make_demo_client()
    body = client.post("/demo/analyze").json()
    assert isinstance(body["user_stories"], list)


def test_demo_analyze_user_story_shape():
    """Each user story must have id, role, feature, benefit, priority."""
    client = _make_demo_client()
    body = client.post("/demo/analyze").json()
    for story in body["user_stories"]:
        for key in ("id", "role", "feature", "benefit", "priority"):
            assert key in story, f"User story missing key: {key}"


def test_demo_analyze_acceptance_criteria_is_list():
    """acceptance_criteria must be a list."""
    client = _make_demo_client()
    body = client.post("/demo/analyze").json()
    assert isinstance(body["acceptance_criteria"], list)


def test_demo_analyze_gap_flags_is_list():
    """gap_flags must be a list."""
    client = _make_demo_client()
    body = client.post("/demo/analyze").json()
    assert isinstance(body["gap_flags"], list)


def test_demo_analyze_gap_flag_shape():
    """Each gap flag must have type, severity, description."""
    client = _make_demo_client()
    body = client.post("/demo/analyze").json()
    for flag in body["gap_flags"]:
        for key in ("type", "severity", "description"):
            assert key in flag, f"Gap flag missing key: {key}"


# ---------------------------------------------------------------------------
# 15.4 — POST /demo/analyze makes no calls to gemini_engine or ocr_engine
# Requirements: 10.3
# ---------------------------------------------------------------------------

def test_demo_analyze_does_not_call_gemini():
    """POST /demo/analyze must NOT call gemini_engine.analyze."""
    import gemini_engine as _gem
    import ocr_engine as _ocr

    mock_db = AsyncMock()

    async def _ok_get_session():
        yield mock_db

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_ok_get_session),
        patch("requirement_summarizer_app.validate_env_vars"),
        patch("database.init_db", new=AsyncMock()),
        patch.object(_gem, "analyze", new=AsyncMock()) as mock_gemini,
        patch.object(_ocr, "extract_text", return_value=MagicMock()) as mock_ocr,
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        response = client.post("/demo/analyze")

    assert response.status_code == 200
    mock_gemini.assert_not_called()
    mock_ocr.assert_not_called()
