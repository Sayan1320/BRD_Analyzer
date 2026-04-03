"""
Property-based tests for Spec 08 - Observability.
Tasks 10.1-10.2: Hypothesis properties for structured logging and metrics.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_analyze_mocks():
    """Return standard mocks for the /analyze endpoint."""
    from ocr_engine import ExtractionResult

    mock_session_record = MagicMock()
    mock_session_record.id = "00000000-0000-0000-0000-000000000001"
    mock_db = AsyncMock()
    extraction = ExtractionResult(text="hello world", char_count=11, page_count=1)
    analysis_json = json.dumps({
        "executive_summary": "summary",
        "user_stories": [],
        "acceptance_criteria": [],
        "gap_flags": [],
    })
    return mock_session_record, mock_db, extraction, analysis_json


# ---------------------------------------------------------------------------
# P1: Every analyze log entry contains request_id
# Validates: Requirements 8.3, 8.8
# ---------------------------------------------------------------------------

@given(
    filename=st.text(
        min_size=1,
        max_size=50,
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters="._-",
        ),
    )
)
@settings(max_examples=25, deadline=None)
def test_p1_all_analyze_log_entries_share_request_id(filename: str):
    """
    **Validates: Requirements 8.3, 8.8**

    Property: For any valid filename, all log entries emitted by the /analyze
    endpoint during a single request share the same request_id value.
    """
    import ocr_engine as _ocr
    import gemini_engine as _gem
    import requirement_summarizer_app as _rs_module
    from fastapi.testclient import TestClient

    mock_session_record, mock_db, extraction, analysis_json = _make_analyze_mocks()

    async def _ok_get_session():
        yield mock_db

    captured_log_calls: list[dict] = []

    class _CaptureBoundLogger:
        def __init__(self, bound_request_id: str):
            self._request_id = bound_request_id

        def info(self, event: str, **kwargs):
            captured_log_calls.append({"event": event, "request_id": self._request_id, **kwargs})

        def error(self, event: str, **kwargs):
            captured_log_calls.append({"event": event, "request_id": self._request_id, **kwargs})

    class _CaptureLogger:
        def bind(self, **kwargs):
            return _CaptureBoundLogger(kwargs.get("request_id", ""))

        def info(self, event: str, **kwargs):
            pass

        def error(self, event: str, **kwargs):
            pass

    def _fake_get_logger(name: str):
        if name == "analyze":
            return _CaptureLogger()
        return MagicMock()

    # Ensure filename has a valid extension so the endpoint doesn't reject it
    safe_filename = filename.rstrip(".") + ".txt"

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_ok_get_session),
        patch("requirement_summarizer_app.create_session_record", new=AsyncMock(return_value=mock_session_record)),
        patch("requirement_summarizer_app.update_session_extraction", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_result", new=AsyncMock()),
        patch("requirement_summarizer_app.get_logger", side_effect=_fake_get_logger),
        patch.object(_ocr, "extract_text", return_value=extraction),
        patch.object(
            _gem._client.aio.models,
            "generate_content",
            new=AsyncMock(return_value=MagicMock(text=analysis_json)),
        ),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        response = client.post(
            "/analyze",
            files={"file": (safe_filename, io.BytesIO(b"hello world"), "text/plain")},
        )

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )

    # Property: at least the core log events were emitted
    assert len(captured_log_calls) >= 1, "Expected at least one log entry from /analyze"

    # Property: every captured log entry has a request_id key
    for entry in captured_log_calls:
        assert "request_id" in entry, (
            f"Log entry missing request_id: {entry}"
        )
        assert entry["request_id"], (
            f"Log entry has empty request_id: {entry}"
        )

    # Property: all log entries share the same request_id
    request_ids = {entry["request_id"] for entry in captured_log_calls}
    assert len(request_ids) == 1, (
        f"Expected all log entries to share one request_id, got: {request_ids}"
    )

    # Property: request_id in response matches the one in logs
    body = response.json()
    assert "request_id" in body, "Response JSON missing request_id"
    assert body["request_id"] == next(iter(request_ids)), (
        f"Response request_id {body['request_id']!r} does not match "
        f"log request_id {next(iter(request_ids))!r}"
    )


# ---------------------------------------------------------------------------
# P2: get_metrics_summary values are always non-negative integers
# Validates: Requirements 8.7
# ---------------------------------------------------------------------------

@given(count=st.integers(min_value=0, max_value=10000))
@settings(max_examples=50)
@pytest.mark.asyncio
async def test_p2_metrics_summary_values_are_non_negative(count: int):
    """
    **Validates: Requirements 8.7**

    Property: For any non-negative integer returned by the DB, all numeric
    fields in get_metrics_summary() are >= 0 and model_breakdown is a dict.
    """
    from database import get_metrics_summary

    mock_scalar_result = MagicMock()
    mock_scalar_result.scalar.return_value = count
    mock_scalar_result.all.return_value = []

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_scalar_result)

    result = await get_metrics_summary(mock_db)

    numeric_fields = [
        "total_analyses",
        "avg_tokens",
        "avg_processing_ms",
        "total_voice_requests",
        "error_count",
    ]

    for field in numeric_fields:
        assert field in result, f"Missing field: {field}"
        value = result[field]
        assert isinstance(value, int), (
            f"Field {field!r} should be int, got {type(value).__name__}: {value!r}"
        )
        assert value >= 0, (
            f"Field {field!r} should be >= 0, got {value!r} (DB count={count})"
        )

    assert "model_breakdown" in result, "Missing field: model_breakdown"
    assert isinstance(result["model_breakdown"], dict), (
        f"model_breakdown should be dict, got {type(result['model_breakdown']).__name__}"
    )
