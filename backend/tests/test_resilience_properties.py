"""
Property-based tests for Spec 09 — Rate Limiting and Resilience.

P1: Gemini retry count never exceeds 3 attempts (Req 9.4)
P2: Truncated text length always <= 100000 characters (Req 9.6)
P3: db_persisted field in /analyze response is always boolean (Req 9.7)
"""

from __future__ import annotations

import io
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Ensure backend/ is on the path
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from ocr_engine import ExtractionResult


# ---------------------------------------------------------------------------
# P1: Gemini retry count never exceeds 3 attempts
# Validates: Requirements 9.4
# ---------------------------------------------------------------------------

@given(failure_count=st.integers(min_value=1, max_value=10))
@settings(max_examples=50, deadline=None)
@pytest.mark.asyncio
async def test_gemini_retry_count_never_exceeds_3(failure_count: int):
    """
    **Validates: Requirements 9.4**

    P1: Gemini retry count never exceeds 3 attempts regardless of failure count.
    """
    import google.api_core.exceptions as gcp_exc
    import gemini_engine as _gem

    call_count = [0]

    async def _flaky_generate(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] <= failure_count:
            raise gcp_exc.ServiceUnavailable("temporary")
        mock_resp = MagicMock()
        mock_resp.text = '{"executive_summary": "ok", "user_stories": [], "acceptance_criteria": [], "gap_flags": []}'
        return mock_resp

    call_count[0] = 0  # reset for each hypothesis example
    try:
        with patch.object(_gem._client.aio.models, "generate_content", side_effect=_flaky_generate):
            await _gem.analyze("some text")
    except Exception:
        pass  # expected when failure_count >= 3

    assert call_count[0] <= 3, f"Expected at most 3 calls, got {call_count[0]}"


# ---------------------------------------------------------------------------
# P2: Truncated text length always <= 100000 characters
# Validates: Requirements 9.6
# ---------------------------------------------------------------------------

@given(document_text=st.text(min_size=0, max_size=200_000))
@settings(max_examples=50, deadline=None)
@pytest.mark.asyncio
async def test_truncated_text_length_always_lte_100000(document_text: str):
    """
    **Validates: Requirements 9.6**

    P2: Text passed to Gemini is always <= 100000 characters.
    """
    import gemini_engine as _gem

    captured_prompt = []

    async def _capture_call(prompt):
        captured_prompt.append(prompt)
        return '{"executive_summary": "ok", "user_stories": [], "acceptance_criteria": [], "gap_flags": []}'

    with patch.object(_gem, "_call_gemini", side_effect=_capture_call):
        await _gem.analyze(document_text)

    assert len(captured_prompt) == 1
    # The text portion must be <= 100000 — verify the original text was truncated if needed
    expected_text_in_prompt = document_text[:100_000]
    assert expected_text_in_prompt in captured_prompt[0]
    # And the full text (if > 100000) must NOT be in the prompt
    if len(document_text) > 100_000:
        assert document_text not in captured_prompt[0]


# ---------------------------------------------------------------------------
# P3: db_persisted field in /analyze response is always boolean
# Validates: Requirements 9.7
# ---------------------------------------------------------------------------

@given(db_succeeds=st.booleans())
@settings(max_examples=50, deadline=None)
def test_db_persisted_is_always_boolean(db_succeeds: bool):
    """
    **Validates: Requirements 9.7**

    P3: db_persisted field in /analyze response is always a boolean.
    """
    import ocr_engine as _ocr
    import gemini_engine as _gem
    import requirement_summarizer_app as _rs_module
    from fastapi.testclient import TestClient
    from database import DatabaseError

    mock_session_record = MagicMock()
    mock_session_record.id = "00000000-0000-0000-0000-000000000001"
    mock_db = AsyncMock()

    analysis_json = json.dumps({
        "executive_summary": "summary",
        "user_stories": [],
        "acceptance_criteria": [],
        "gap_flags": [],
    })

    if db_succeeds:
        async def _get_session():
            yield mock_db
    else:
        async def _get_session():
            raise DatabaseError("connection failed")
            yield

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_get_session),
        patch("requirement_summarizer_app.create_session_record", new=AsyncMock(return_value=mock_session_record)),
        patch("requirement_summarizer_app.save_document_metadata", new=AsyncMock(return_value=MagicMock(id="doc-1"))),
        patch("requirement_summarizer_app.update_session_extraction", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_result", new=AsyncMock()),
        patch("requirement_summarizer_app.save_analysis_result", new=AsyncMock()),
        patch("requirement_summarizer_app.update_document_status", new=AsyncMock()),
        patch.object(_ocr, "extract_text", return_value=ExtractionResult(text="hello world", char_count=11, page_count=1)),
        patch.object(_gem._client.aio.models, "generate_content", new=AsyncMock(return_value=MagicMock(text=analysis_json))),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        resp = client.post(
            "/analyze",
            files={"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "db_persisted" in body
    assert type(body["db_persisted"]) is bool
