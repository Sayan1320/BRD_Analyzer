"""
Unit tests for the Requirement Summarizer service.
Covers tasks 9.1–9.8.
"""

from __future__ import annotations

import io
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Ensure backend/ is on the path
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from fastapi.testclient import TestClient
from ocr_engine import ExtractionResult
from gemini_engine import AnalysisResult, UserStory
import requirement_summarizer_app as _rs_module


# ---------------------------------------------------------------------------
# Helpers — build a synchronous TestClient with all externals mocked
# ---------------------------------------------------------------------------

def _make_test_client(
    *,
    extraction: ExtractionResult | None = None,
    analysis: AnalysisResult | None = None,
    db_raises: Exception | None = None,
) -> TestClient:
    """
    Return a TestClient for rs_app with DB, OCR, and Gemini mocked.

    - extraction: what ocr_engine.extract_text() returns (default: small valid result)
    - analysis:   what gemini_engine.analyze() returns (default: minimal valid result)
    - db_raises:  if set, get_session raises this exception instead of yielding a session
    """
    if extraction is None:
        extraction = ExtractionResult(text="hello world", char_count=11, page_count=1)
    if analysis is None:
        analysis = AnalysisResult(
            executive_summary="summary",
            user_stories=[],
            acceptance_criteria=[],
            gap_flags=[],
        )

    mock_session_record = MagicMock()
    mock_session_record.id = "00000000-0000-0000-0000-000000000001"
    mock_doc = MagicMock()
    mock_doc.id = "00000000-0000-0000-0000-000000000002"
    mock_db = AsyncMock()
    mock_db.add = MagicMock()  # db.add is sync

    if db_raises is not None:
        async def _failing_get_session():
            raise db_raises
            yield  # make it a generator

        get_session_patch = patch(
            "requirement_summarizer_app.get_session",
            side_effect=_failing_get_session,
        )
    else:
        async def _ok_get_session():
            yield mock_db

        get_session_patch = patch(
            "requirement_summarizer_app.get_session",
            side_effect=_ok_get_session,
        )

    import ocr_engine as _ocr
    import gemini_engine as _gem

    with (
        get_session_patch,
        patch("requirement_summarizer_app.create_session_record", new=AsyncMock(return_value=mock_session_record)),
        patch("requirement_summarizer_app.save_document_metadata", new=AsyncMock(return_value=mock_doc)),
        patch("requirement_summarizer_app.save_analysis_result", new=AsyncMock(return_value=MagicMock())),
        patch("requirement_summarizer_app.update_document_status", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_extraction", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_result", new=AsyncMock()),
        patch.object(_ocr, "extract_text", return_value=extraction),
        patch.object(
            _gem._client.aio.models,
            "generate_content",
            new=AsyncMock(return_value=MagicMock(text=json.dumps({
                "executive_summary": analysis.executive_summary,
                "user_stories": [],
                "acceptance_criteria": list(analysis.acceptance_criteria),
                "gap_flags": list(analysis.gap_flags),
            }))),
        ),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        yield client


# ---------------------------------------------------------------------------
# 9.1 — GET /health returns {"status": "ok"} with HTTP 200
# Requirements: 4.1
# ---------------------------------------------------------------------------

def test_health_returns_ok():
    """GET /health must return HTTP 200 with the enhanced component status body."""
    # Patch lifespan hooks so the app starts without real env vars or DB
    with (
        patch("requirement_summarizer_app.validate_env_vars"),
        patch("database.init_db", new=AsyncMock()),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert "status" in body
    assert body["service"] == "ai-req-summarizer"
    assert body["version"] == "2.0"
    assert "components" in body
    assert "uptime_seconds" in body
    assert isinstance(body["uptime_seconds"], int)


# ---------------------------------------------------------------------------
# 9.2 — POST /analyze with valid .txt returns expected response shape
# Requirements: 1.1, 1.4, 1.5, 2.2
# ---------------------------------------------------------------------------

def test_analyze_valid_txt_response_shape():
    """
    POST /analyze with a small .txt file must return HTTP 200 with a body
    containing session_id, filename, char_count, page_count, and analysis
    with all four required keys.
    """
    import ocr_engine as _ocr
    import gemini_engine as _gem

    mock_session_record = MagicMock()
    mock_session_record.id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    mock_doc = MagicMock()
    mock_doc.id = "aaaaaaaa-bbbb-cccc-dddd-ffffffffffff"
    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    async def _ok_get_session():
        yield mock_db

    extraction = ExtractionResult(text="some requirements text", char_count=22, page_count=1)
    analysis_json = json.dumps({
        "executive_summary": "A brief summary",
        "user_stories": [
            {"id": "US-1", "role": "analyst", "feature": "upload", "benefit": "save time", "priority": "high"}
        ],
        "acceptance_criteria": ["AC-1: system accepts PDF"],
        "gap_flags": ["Missing non-functional requirements"],
    })

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_ok_get_session),
        patch("requirement_summarizer_app.create_session_record", new=AsyncMock(return_value=mock_session_record)),
        patch("requirement_summarizer_app.save_document_metadata", new=AsyncMock(return_value=mock_doc)),
        patch("requirement_summarizer_app.save_analysis_result", new=AsyncMock(return_value=MagicMock())),
        patch("requirement_summarizer_app.update_document_status", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_extraction", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_result", new=AsyncMock()),
        patch.object(_ocr, "extract_text", return_value=extraction),
        patch.object(_gem._client.aio.models, "generate_content", new=AsyncMock(return_value=MagicMock(text=analysis_json))),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        response = client.post(
            "/analyze",
            files={"file": ("requirements.txt", io.BytesIO(b"some requirements text"), "text/plain")},
        )

    assert response.status_code == 200
    body = response.json()

    # Top-level keys
    assert "session_id" in body
    assert "filename" in body
    assert "char_count" in body
    assert "page_count" in body
    assert "analysis" in body

    # Analysis sub-keys
    analysis = body["analysis"]
    assert "executive_summary" in analysis
    assert "user_stories" in analysis
    assert "acceptance_criteria" in analysis
    assert "gap_flags" in analysis

    # Extraction counts match mocked values
    assert body["char_count"] == 22
    assert body["page_count"] == 1
    assert body["filename"] == "requirements.txt"


# ---------------------------------------------------------------------------
# 9.3 — POST /analyze with unsupported extension returns HTTP 415
# Requirements: 1.3
# ---------------------------------------------------------------------------

def test_analyze_unsupported_extension_returns_415():
    """POST /analyze with a .csv file must return HTTP 415."""
    import ocr_engine as _ocr
    import gemini_engine as _gem

    mock_db = AsyncMock()

    async def _ok_get_session():
        yield mock_db

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_ok_get_session),
        patch("requirement_summarizer_app.create_session_record", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_extraction", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_result", new=AsyncMock()),
        patch.object(_ocr, "extract_text", return_value=ExtractionResult("", 0, 0)),
        patch.object(_gem._client.aio.models, "generate_content", new=AsyncMock()),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        response = client.post(
            "/analyze",
            files={"file": ("data.csv", io.BytesIO(b"col1,col2\n1,2"), "text/csv")},
        )

    assert response.status_code == 415


# ---------------------------------------------------------------------------
# 9.4 — POST /analyze with file > 20 MB returns HTTP 413
# Requirements: 1.2
# ---------------------------------------------------------------------------

def test_analyze_oversized_file_returns_413():
    """POST /analyze with a file exceeding 20 MB must return HTTP 413."""
    import ocr_engine as _ocr
    import gemini_engine as _gem

    mock_db = AsyncMock()

    async def _ok_get_session():
        yield mock_db

    oversized_content = b"x" * (20 * 1024 * 1024 + 1)  # 20 MB + 1 byte

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_ok_get_session),
        patch("requirement_summarizer_app.create_session_record", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_extraction", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_result", new=AsyncMock()),
        patch.object(_ocr, "extract_text", return_value=ExtractionResult("", 0, 0)),
        patch.object(_gem._client.aio.models, "generate_content", new=AsyncMock()),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        response = client.post(
            "/analyze",
            files={"file": ("big.txt", io.BytesIO(oversized_content), "text/plain")},
        )

    assert response.status_code == 413


# ---------------------------------------------------------------------------
# 9.5 — gemini_engine.analyze() with mocked Gemini returns correct AnalysisResult
# Requirements: 2.1, 2.2, 2.3
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gemini_analyze_valid_json_produces_correct_result():
    """
    gemini_engine.analyze() with a mocked Gemini response returning valid JSON
    must produce an AnalysisResult with correct field values.
    """
    import gemini_engine as _gem

    valid_json = json.dumps({
        "executive_summary": "The system handles document uploads.",
        "user_stories": [
            {
                "id": "US-1",
                "role": "analyst",
                "feature": "upload documents",
                "benefit": "automate analysis",
                "priority": "high",
            }
        ],
        "acceptance_criteria": ["Files under 20 MB are accepted"],
        "gap_flags": ["No mention of authentication"],
    })

    mock_response = MagicMock()
    mock_response.text = valid_json

    with patch.object(
        _gem._client.aio.models,
        "generate_content",
        new=AsyncMock(return_value=mock_response),
    ):
        result = await _gem.analyze("some extracted text")

    assert isinstance(result, AnalysisResult)
    assert result.executive_summary == "The system handles document uploads."
    assert len(result.user_stories) == 1

    story = result.user_stories[0]
    assert isinstance(story, UserStory)
    assert story.id == "US-1"
    assert story.role == "analyst"
    assert story.feature == "upload documents"
    assert story.benefit == "automate analysis"
    assert story.priority == "high"

    assert result.acceptance_criteria == ["Files under 20 MB are accepted"]
    assert result.gap_flags == ["No mention of authentication"]


# ---------------------------------------------------------------------------
# 9.6 — ocr_engine.extract_text() with empty bytes returns ExtractionResult("", 0, 0)
# Requirements: 5.4
# ---------------------------------------------------------------------------

def test_ocr_extract_text_empty_bytes_returns_empty_result():
    """
    ocr_engine.extract_text() called with empty bytes must return
    ExtractionResult(text="", char_count=0, page_count=0) without raising.
    """
    from ocr_engine import extract_text

    result = extract_text(b"", "document.txt")

    assert result.text == ""
    assert result.char_count == 0
    assert result.page_count == 0


# ---------------------------------------------------------------------------
# 9.7 — validate_env_vars() raises RuntimeError when each required var is missing
# Requirements: 4.2, 4.3
# ---------------------------------------------------------------------------

REQUIRED_VARS = [
    "GOOGLE_AI_API_KEY",
    "LLAMA_CLOUD_API_KEY",
    "ALLOYDB_INSTANCE_URI",
    "DB_USER",
    "DB_PASS",
    "DB_NAME",
]

_FULL_ENV = {var: "dummy_value" for var in REQUIRED_VARS}


@pytest.mark.parametrize("missing_var", REQUIRED_VARS)
def test_validate_env_vars_raises_when_var_missing(missing_var: str):
    """
    validate_env_vars() must raise RuntimeError when any single required
    environment variable is absent from the environment.
    """
    from requirement_summarizer_helpers import validate_env_vars

    env_without_var = {k: v for k, v in _FULL_ENV.items() if k != missing_var}

    with pytest.raises(RuntimeError) as exc_info:
        validate_env_vars(env=env_without_var)

    assert missing_var in str(exc_info.value), (
        f"Expected RuntimeError message to mention '{missing_var}', "
        f"got: {exc_info.value}"
    )


# ---------------------------------------------------------------------------
# 9.8 — DB pool unavailable: circuit breaker returns 200 with db_persisted=False
# Requirements: 9.7
# ---------------------------------------------------------------------------

def test_analyze_db_unavailable_returns_result_with_db_persisted_false():
    """
    When get_session raises a connection error, POST /analyze must still return
    HTTP 200 with the analysis result and db_persisted=False (circuit breaker).
    """
    import ocr_engine as _ocr
    import gemini_engine as _gem
    from database import DatabaseError

    async def _failing_get_session():
        raise DatabaseError("Connection pool unavailable")
        yield  # make it an async generator

    analysis_json = json.dumps({
        "executive_summary": "summary",
        "user_stories": [],
        "acceptance_criteria": [],
        "gap_flags": [],
    })

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_failing_get_session),
        patch("requirement_summarizer_app.create_session_record", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_extraction", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_result", new=AsyncMock()),
        patch.object(_ocr, "extract_text", return_value=ExtractionResult("hello world", 11, 1)),
        patch.object(_gem._client.aio.models, "generate_content", new=AsyncMock(return_value=MagicMock(text=analysis_json))),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        response = client.post(
            "/analyze",
            files={"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["db_persisted"] is False
    assert body["session_id"] == "unavailable"
    assert body["document_id"] == "unavailable"
    assert "analysis" in body
