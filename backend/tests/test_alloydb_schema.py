"""
Unit tests for AlloyDB schema functions and endpoints.

Tests 6.1–6.6: database.py functions (save_document_metadata, save_analysis_result,
               update_document_status, get_history) using AsyncMock for the DB session.
Tests 6.7–6.10: HTTP endpoint tests for /history and /analyze.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# 6.1  save_document_metadata returns DocumentMetadata with status='processing'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_document_metadata_returns_processing_status():
    """6.1 save_document_metadata should create a record with status='processing'."""
    from database import save_document_metadata

    db = AsyncMock()
    db.flush = AsyncMock()

    result = await save_document_metadata(
        db,
        session_id=uuid.uuid4(),
        filename="test.pdf",
        file_type="pdf",
        file_size_kb=100,
        page_count=5,
    )

    assert result.status == "processing"
    db.add.assert_called_once()
    db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# 6.2  save_analysis_result extracts all four JSON fields correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_analysis_result_extracts_all_four_fields():
    """6.2 save_analysis_result should populate all four JSONB fields from result_dict."""
    from database import save_analysis_result

    db = AsyncMock()
    db.flush = AsyncMock()

    result_dict = {
        "executive_summary": "This is the summary.",
        "user_stories": [{"id": "US-1", "role": "user"}],
        "acceptance_criteria": [{"id": "AC-1", "criteria": "must work"}],
        "gap_flags": [{"flag": "missing auth"}],
    }

    result = await save_analysis_result(
        db,
        document_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        result_dict=result_dict,
        tokens_used=100,
        processing_time_ms=500,
        model_used="gemini",
    )

    assert result.executive_summary == "This is the summary."
    assert result.user_stories == [{"id": "US-1", "role": "user"}]
    assert result.acceptance_criteria == [{"id": "AC-1", "criteria": "must work"}]
    assert result.gap_flags == [{"flag": "missing auth"}]
    db.add.assert_called_once()
    db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# 6.3  update_document_status raises ValueError for invalid status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_document_status_raises_for_invalid_status():
    """6.3 update_document_status should raise ValueError for an invalid status string."""
    from database import update_document_status

    db = AsyncMock()

    with pytest.raises(ValueError):
        await update_document_status(db, uuid.uuid4(), "invalid_status")


# ---------------------------------------------------------------------------
# 6.4  update_document_status accepts all three valid statuses
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_document_status_accepts_all_valid_statuses():
    """6.4 update_document_status should not raise for 'processing', 'completed', 'failed'."""
    from database import update_document_status

    for status in ("processing", "completed", "failed"):
        db = AsyncMock()
        db.execute = AsyncMock()
        # Should not raise
        await update_document_status(db, uuid.uuid4(), status)


# ---------------------------------------------------------------------------
# 6.5  get_history enforces max limit of 50
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_history_clamps_limit_to_50():
    """6.5 get_history should clamp any limit > 50 to 50 internally."""
    from database import get_history

    execute_result = MagicMock()
    execute_result.all.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=execute_result)

    result = await get_history(db, limit=999)

    # Result must be a list (empty since mock returns [])
    assert isinstance(result, list)
    assert len(result) <= 50

    # Verify execute was called and the statement has limit clamped to 50
    db.execute.assert_awaited_once()
    stmt = db.execute.call_args[0][0]
    # The compiled statement should contain LIMIT 50 (not 999)
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "50" in compiled
    assert "999" not in compiled


# ---------------------------------------------------------------------------
# 6.6  get_history returns empty list when no records
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_history_returns_empty_list_when_no_records():
    """6.6 get_history should return [] when the DB has no matching rows."""
    from database import get_history

    execute_result = MagicMock()
    execute_result.all.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=execute_result)

    result = await get_history(db, limit=10)

    assert result == []


# ---------------------------------------------------------------------------
# HTTP test helpers
# ---------------------------------------------------------------------------

def _make_mock_doc(doc_id: uuid.UUID | None = None) -> MagicMock:
    mock = MagicMock()
    mock.id = doc_id or uuid.uuid4()
    return mock


def _make_mock_session_record(session_id: str | None = None) -> MagicMock:
    mock = MagicMock()
    mock.id = session_id or str(uuid.uuid4())
    return mock


# ---------------------------------------------------------------------------
# 6.7  GET /history returns 400 for limit > 50
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_endpoint_returns_400_for_limit_over_50():
    """6.7 GET /history?limit=51 should return HTTP 400."""
    import requirement_summarizer_app as _rs_module
    from httpx import AsyncClient, ASGITransport

    db_mock = AsyncMock()

    async def _fake_get_session():
        yield db_mock

    with patch("requirement_summarizer_app.get_session", side_effect=_fake_get_session):
        transport = ASGITransport(app=_rs_module.rs_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/history?limit=51")

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 6.8  GET /history returns 400 for limit < 1
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_endpoint_returns_400_for_limit_under_1():
    """6.8 GET /history?limit=0 should return HTTP 400."""
    import requirement_summarizer_app as _rs_module
    from httpx import AsyncClient, ASGITransport

    db_mock = AsyncMock()

    async def _fake_get_session():
        yield db_mock

    with patch("requirement_summarizer_app.get_session", side_effect=_fake_get_session):
        transport = ASGITransport(app=_rs_module.rs_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/history?limit=0")

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 6.9  POST /analyze response includes document_id and session_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_response_includes_document_id_and_session_id():
    """6.9 POST /analyze should return JSON with 'document_id' and 'session_id' keys."""
    import requirement_summarizer_app as _rs_module
    from httpx import AsyncClient, ASGITransport
    from ocr_engine import ExtractionResult
    from gemini_engine import AnalysisResult as GeminiAnalysisResult

    doc_id = uuid.uuid4()
    session_id = uuid.uuid4()

    mock_doc = _make_mock_doc(doc_id)
    mock_session = _make_mock_session_record(str(session_id))
    mock_db = AsyncMock()

    async def _fake_get_session():
        yield mock_db

    mock_extraction = ExtractionResult(text="some text content", char_count=17, page_count=1)
    mock_analysis = GeminiAnalysisResult(
        executive_summary="summary",
        user_stories=[],
        acceptance_criteria=[],
        gap_flags=[],
    )

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_fake_get_session),
        patch("requirement_summarizer_app.create_session_record", new=AsyncMock(return_value=mock_session)),
        patch("requirement_summarizer_app.save_document_metadata", new=AsyncMock(return_value=mock_doc)),
        patch("requirement_summarizer_app.save_analysis_result", new=AsyncMock()),
        patch("requirement_summarizer_app.update_document_status", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_extraction", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_result", new=AsyncMock()),
        patch("ocr_engine.extract_text", return_value=mock_extraction),
        patch("gemini_engine.analyze", new=AsyncMock(return_value=mock_analysis)),
        patch("requirement_summarizer_app.AuditLog", MagicMock()),
    ):
        transport = ASGITransport(app=_rs_module.rs_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            pdf_bytes = b"%PDF-1.4 fake pdf content"
            response = await client.post(
                "/analyze",
                files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
            )

    assert response.status_code == 200
    body = response.json()
    assert "document_id" in body
    assert "session_id" in body


# ---------------------------------------------------------------------------
# 6.10  POST /analyze sets status='failed' when Gemini raises exception
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_sets_failed_status_when_gemini_raises():
    """6.10 POST /analyze should call update_document_status('failed') and return 502 when Gemini raises."""
    import requirement_summarizer_app as _rs_module
    from httpx import AsyncClient, ASGITransport
    from ocr_engine import ExtractionResult

    doc_id = uuid.uuid4()
    session_id = uuid.uuid4()

    mock_doc = _make_mock_doc(doc_id)
    mock_session = _make_mock_session_record(str(session_id))
    mock_db = AsyncMock()
    mock_update_status = AsyncMock()

    async def _fake_get_session():
        yield mock_db

    async def _gemini_raises(*args, **kwargs):
        raise Exception("Gemini service unavailable")

    mock_extraction = ExtractionResult(text="some text content", char_count=17, page_count=1)

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_fake_get_session),
        patch("requirement_summarizer_app.create_session_record", new=AsyncMock(return_value=mock_session)),
        patch("requirement_summarizer_app.save_document_metadata", new=AsyncMock(return_value=mock_doc)),
        patch("requirement_summarizer_app.save_analysis_result", new=AsyncMock()),
        patch("requirement_summarizer_app.update_document_status", new=mock_update_status),
        patch("requirement_summarizer_app.update_session_extraction", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_result", new=AsyncMock()),
        patch("ocr_engine.extract_text", return_value=mock_extraction),
        patch("gemini_engine.analyze", new=_gemini_raises),
        patch("requirement_summarizer_app.AuditLog", MagicMock()),
    ):
        transport = ASGITransport(app=_rs_module.rs_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            pdf_bytes = b"%PDF-1.4 fake pdf content"
            response = await client.post(
                "/analyze",
                files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
            )

    assert response.status_code == 502

    # Verify update_document_status was called with 'failed'
    called_with_failed = any(
        call.args[1] == "failed" or (len(call.args) > 1 and call.args[1] == "failed")
        or call.kwargs.get("status") == "failed"
        for call in mock_update_status.call_args_list
    )
    # Also check positional: update_document_status(db, doc_id, 'failed')
    called_with_failed = called_with_failed or any(
        "failed" in str(call) for call in mock_update_status.call_args_list
    )
    assert called_with_failed, (
        f"Expected update_document_status to be called with 'failed', "
        f"but calls were: {mock_update_status.call_args_list}"
    )
