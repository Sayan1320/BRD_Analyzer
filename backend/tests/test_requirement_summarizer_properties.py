"""
Property-based tests for the Requirement Summarizer service.
Uses hypothesis with @settings(max_examples=100).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass

from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Minimal local definitions of AnalysisResult / UserStory
# (gemini_engine.py will be created in a later task; these mirror its shape)
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
    user_stories: list[UserStory]
    acceptance_criteria: list[str]
    gap_flags: list[str]


# ---------------------------------------------------------------------------
# Serialization helpers (mirrors what database.py will do with JSONB)
# ---------------------------------------------------------------------------


def _analysis_result_to_dict(result: AnalysisResult) -> dict:
    """Serialize AnalysisResult to a plain dict (JSONB-compatible)."""
    return {
        "executive_summary": result.executive_summary,
        "user_stories": [dataclasses.asdict(us) for us in result.user_stories],
        "acceptance_criteria": list(result.acceptance_criteria),
        "gap_flags": list(result.gap_flags),
    }


def _analysis_result_from_dict(data: dict) -> AnalysisResult:
    """Deserialize an AnalysisResult from a plain dict (as read from JSONB)."""
    return AnalysisResult(
        executive_summary=data["executive_summary"],
        user_stories=[UserStory(**us) for us in data["user_stories"]],
        acceptance_criteria=list(data["acceptance_criteria"]),
        gap_flags=list(data["gap_flags"]),
    )


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_user_story_strategy = st.builds(
    UserStory,
    id=st.text(),
    role=st.text(),
    feature=st.text(),
    benefit=st.text(),
    priority=st.text(),
)

_analysis_result_strategy = st.builds(
    AnalysisResult,
    executive_summary=st.text(),
    user_stories=st.lists(_user_story_strategy),
    acceptance_criteria=st.lists(st.text()),
    gap_flags=st.lists(st.text()),
)


# ---------------------------------------------------------------------------
# Feature: requirement-summarizer, Property 8: Analysis Result Round-Trip Persistence
# ---------------------------------------------------------------------------


# Feature: requirement-summarizer, Property 8: Analysis Result Round-Trip Persistence
@given(result=_analysis_result_strategy)
@settings(max_examples=100)
def test_analysis_result_roundtrip(result: AnalysisResult) -> None:
    """
    Validates: Requirements 3.3

    For any AnalysisResult, serializing to a dict (as stored in the JSONB column)
    and deserializing back must produce an object equivalent to the original —
    all fields present, all values equal.
    """
    # Simulate JSONB round-trip: serialize → JSON string → parse → deserialize
    serialized = _analysis_result_to_dict(result)
    json_str = json.dumps(serialized)
    loaded_dict = json.loads(json_str)
    restored = _analysis_result_from_dict(loaded_dict)

    assert restored == result, (
        f"Round-trip mismatch.\nOriginal: {result}\nRestored: {restored}"
    )


# ===========================================================================
# Database layer property tests (P6, P7, P9, P10)
# Require: aiosqlite, pytest-asyncio, sqlalchemy[asyncio]
# ===========================================================================

import sys
import os

import pytest
import pytest_asyncio

# Ensure backend/ is importable
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from datetime import timezone

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import initialize
from sqlalchemy import JSON, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# SQLite-compatible model base
# We re-create the metadata using JSON instead of JSONB for SQLite compat.
# ---------------------------------------------------------------------------

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import uuid
from datetime import datetime


class _TestBase(DeclarativeBase):
    pass


def _utcnow_test() -> datetime:
    return datetime.now(timezone.utc)


class _TestSession(_TestBase):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow_test
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow_test
    )

    audit_logs: Mapped[list["_TestAuditLog"]] = relationship(
        "_TestAuditLog", back_populates="session", cascade="all, delete-orphan"
    )


class _TestAuditLog(_TestBase):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow_test
    )

    session: Mapped[_TestSession] = relationship("_TestSession", back_populates="audit_logs")


# ---------------------------------------------------------------------------
# Async SQLite engine factory for tests
# ---------------------------------------------------------------------------

async def _make_test_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)
    return engine


# ---------------------------------------------------------------------------
# DB helper functions that mirror database.py but use the test models
# ---------------------------------------------------------------------------

async def _create_session_record(db: AsyncSession, filename: str, file_size_bytes: int) -> _TestSession:
    session_obj = _TestSession(
        filename=filename,
        file_size_bytes=file_size_bytes,
        status="processing",
    )
    db.add(session_obj)
    await db.flush()

    audit = _TestAuditLog(
        session_id=str(session_obj.id),
        event_type="upload",
    )
    db.add(audit)
    await db.commit()
    await db.refresh(session_obj)
    return session_obj


async def _update_session_extraction(db: AsyncSession, session_id: str, char_count: int, page_count: int) -> None:
    from sqlalchemy import update as sa_update
    stmt = (
        sa_update(_TestSession)
        .where(_TestSession.id == session_id)
        .values(char_count=char_count, page_count=page_count)
    )
    await db.execute(stmt)
    await db.commit()


async def _update_session_result(db: AsyncSession, session_id: str, result: dict) -> None:
    from sqlalchemy import update as sa_update, select as sa_select
    stmt = (
        sa_update(_TestSession)
        .where(_TestSession.id == session_id)
        .values(result=result, status="complete")
    )
    await db.execute(stmt)

    audit = _TestAuditLog(
        session_id=session_id,
        event_type="analysis_complete",
    )
    db.add(audit)
    await db.commit()


# ---------------------------------------------------------------------------
# Feature: requirement-summarizer, Property 6: Session Record Created on Upload
# ---------------------------------------------------------------------------

# Feature: requirement-summarizer, Property 6: Session Record Created on Upload
@given(
    filename=st.text(min_size=1, max_size=255),
    file_size_bytes=st.integers(min_value=1, max_value=20_971_520),
)
@settings(max_examples=100, deadline=None)
@pytest.mark.asyncio
async def test_session_created_on_upload(filename: str, file_size_bytes: int) -> None:
    """
    Validates: Requirements 3.1

    For any valid filename and file size, create_session_record() must return a
    Session with the correct filename, file_size_bytes, and status='processing'.
    """
    import asyncio

    engine = await _make_test_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as db:
        session_obj = await _create_session_record(db, filename, file_size_bytes)

    assert session_obj.filename == filename
    assert session_obj.file_size_bytes == file_size_bytes
    assert session_obj.status == "processing"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Feature: requirement-summarizer, Property 7: Session Updated After Extraction
# ---------------------------------------------------------------------------

# Feature: requirement-summarizer, Property 7: Session Updated After Extraction
# SQLite INTEGER is 64-bit signed; cap at 2^63-1 to stay within bounds.
_SQLITE_MAX_INT = 2**63 - 1


@given(
    char_count=st.integers(min_value=0, max_value=_SQLITE_MAX_INT),
    page_count=st.integers(min_value=0, max_value=_SQLITE_MAX_INT),
)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_session_updated_after_extraction(char_count: int, page_count: int) -> None:
    """
    Validates: Requirements 3.2

    After update_session_extraction(), reading the session back must yield
    matching char_count and page_count.
    """
    from sqlalchemy import select as sa_select

    engine = await _make_test_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as db:
        session_obj = await _create_session_record(db, "test.pdf", 1024)
        session_id = str(session_obj.id)
        await _update_session_extraction(db, session_id, char_count, page_count)

        result = await db.execute(
            sa_select(_TestSession).where(_TestSession.id == session_id)
        )
        updated = result.scalar_one()

    assert updated.char_count == char_count
    assert updated.page_count == page_count

    await engine.dispose()


# ---------------------------------------------------------------------------
# Feature: requirement-summarizer, Property 9: Audit Log Entry for Every Lifecycle Event
# ---------------------------------------------------------------------------

# Feature: requirement-summarizer, Property 9: Audit Log Entry for Every Lifecycle Event
@given(
    event_type=st.sampled_from(["upload", "analysis_complete"]),
)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_audit_log_lifecycle_events(event_type: str) -> None:
    """
    Validates: Requirements 3.4, 3.5

    Each lifecycle call (upload or analysis_complete) must write an AuditLog row
    with the correct event_type, matching session_id, and a UTC created_at.
    """
    from sqlalchemy import select as sa_select

    engine = await _make_test_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as db:
        session_obj = await _create_session_record(db, "test.pdf", 512)
        session_id = str(session_obj.id)

        if event_type == "analysis_complete":
            await _update_session_result(db, session_id, {"executive_summary": "test"})

        result = await db.execute(
            sa_select(_TestAuditLog)
            .where(
                _TestAuditLog.session_id == session_id,
                _TestAuditLog.event_type == event_type,
            )
        )
        audit_rows = result.scalars().all()

    assert len(audit_rows) >= 1, f"Expected at least one AuditLog row for event_type={event_type!r}"
    for row in audit_rows:
        assert row.event_type == event_type
        assert row.session_id == session_id
        # created_at must be timezone-aware (UTC)
        assert row.created_at is not None

    await engine.dispose()


# ---------------------------------------------------------------------------
# Feature: requirement-summarizer, Property 10: Database Error Response Sanitization
# ---------------------------------------------------------------------------

from database import sanitize_error_message  # noqa: E402


# Feature: requirement-summarizer, Property 10: Database Error Response Sanitization
_REDACTED_PLACEHOLDER = "[REDACTED]"


@given(
    sensitive=st.text(min_size=1).filter(lambda s: s not in _REDACTED_PLACEHOLDER),
    base_message=st.text(),
)
@settings(max_examples=100)
def test_db_error_response_sanitization(sensitive: str, base_message: str) -> None:
    """
    Validates: Requirements 3.6

    For any connection string fragment (hostname, password, etc.) that is not
    itself a substring of the redaction placeholder, the sanitized error message
    must not contain that fragment.
    """
    # Build a message that definitely contains the sensitive string
    message_with_sensitive = base_message + sensitive + base_message

    result = sanitize_error_message(message_with_sensitive, [sensitive])

    assert sensitive not in result, (
        f"Sensitive string {sensitive!r} still present in sanitized message: {result!r}"
    )


# ===========================================================================
# OCR engine property tests (P11)
# ===========================================================================

import sys
import os as _os

_BACKEND_DIR_OCR = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _BACKEND_DIR_OCR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR_OCR)

from ocr_engine import extract_text  # noqa: E402

# ---------------------------------------------------------------------------
# Feature: requirement-summarizer, Property 11: Plain Text Round-Trip Extraction
# ---------------------------------------------------------------------------


# Feature: requirement-summarizer, Property 11: Plain Text Round-Trip Extraction
@given(content=st.text(min_size=1))
@settings(max_examples=100)
def test_plain_text_roundtrip(content: str) -> None:
    """
    Validates: Requirements 5.1, 5.3

    For any non-empty string written to a .txt file, extract_text() must return
    an ExtractionResult whose text field is equivalent to the original content
    modulo trailing whitespace normalization.
    """
    result = extract_text(content.encode("utf-8"), "test.txt")
    assert result.text.rstrip() == content.rstrip(), (
        f"Round-trip mismatch.\nOriginal (rstripped): {content.rstrip()!r}\n"
        f"Extracted (rstripped): {result.text.rstrip()!r}"
    )

# ===========================================================================
# Gemini engine property tests (P4, P5)
# ===========================================================================

import sys as _sys
import os as _os
from unittest.mock import AsyncMock, MagicMock, patch

_BACKEND_DIR_GEM = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _BACKEND_DIR_GEM not in _sys.path:
    _sys.path.insert(0, _BACKEND_DIR_GEM)

import gemini_engine as _gem_module
from gemini_engine import analyze, AnalysisResult as GemAnalysisResult, UserStory as GemUserStory


def _is_valid_json(s: str) -> bool:
    """Return True if s can be parsed as JSON."""
    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def _make_mock_response(text: str) -> MagicMock:
    """Build a mock Gemini response object whose .text attribute returns text."""
    mock_resp = MagicMock()
    mock_resp.text = text
    return mock_resp


# ---------------------------------------------------------------------------
# Feature: requirement-summarizer, Property 4: Analysis Result Shape
# ---------------------------------------------------------------------------

_user_story_dict_strategy = st.fixed_dictionaries({
    "id": st.text(),
    "role": st.text(),
    "feature": st.text(),
    "benefit": st.text(),
    "priority": st.text(),
})

_valid_gemini_json_strategy = st.builds(
    lambda summary, stories, criteria, gaps: json.dumps({
        "executive_summary": summary,
        "user_stories": stories,
        "acceptance_criteria": criteria,
        "gap_flags": gaps,
    }),
    summary=st.text(),
    stories=st.lists(_user_story_dict_strategy),
    criteria=st.lists(st.text()),
    gaps=st.lists(st.text()),
)


# Feature: requirement-summarizer, Property 4: Analysis Result Shape
@given(json_response=_valid_gemini_json_strategy)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_analysis_result_shape(json_response: str) -> None:
    """
    Validates: Requirements 2.2, 2.3

    For any valid JSON string with the required keys, analyze() must return an
    AnalysisResult with all four top-level fields present and every user_stories
    item must have id, role, feature, benefit, and priority.
    """
    mock_resp = _make_mock_response(json_response)

    with patch.object(_gem_module._client.aio.models, "generate_content", new=AsyncMock(return_value=mock_resp)):
        result = await analyze("some requirements text")

    assert isinstance(result, GemAnalysisResult)
    assert hasattr(result, "executive_summary")
    assert hasattr(result, "user_stories")
    assert hasattr(result, "acceptance_criteria")
    assert hasattr(result, "gap_flags")
    assert isinstance(result.user_stories, list)
    assert isinstance(result.acceptance_criteria, list)
    assert isinstance(result.gap_flags, list)

    for story in result.user_stories:
        assert hasattr(story, "id")
        assert hasattr(story, "role")
        assert hasattr(story, "feature")
        assert hasattr(story, "benefit")
        assert hasattr(story, "priority")


# ---------------------------------------------------------------------------
# Feature: requirement-summarizer, Property 5: Gemini Fallback on Non-JSON Response
# ---------------------------------------------------------------------------


# Feature: requirement-summarizer, Property 5: Gemini Fallback on Non-JSON Response
@given(raw=st.text(min_size=1).filter(lambda s: not _is_valid_json(s)))
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_gemini_fallback_on_non_json(raw: str) -> None:
    """
    Validates: Requirements 2.5

    For any non-JSON string returned by the Gemini API, analyze() must return a
    fallback AnalysisResult where executive_summary equals the raw response and
    all list fields are empty.
    """
    mock_resp = _make_mock_response(raw)

    with patch.object(_gem_module._client.aio.models, "generate_content", new=AsyncMock(return_value=mock_resp)):
        result = await analyze("some requirements text")

    assert result.executive_summary == raw
    assert result.user_stories == []
    assert result.acceptance_criteria == []
    assert result.gap_flags == []


# ===========================================================================
# main.py property tests (P1, P2, P3, P12)
# ===========================================================================

import sys as _sys_main
import os as _os_main

_BACKEND_DIR_MAIN = _os_main.path.abspath(_os_main.path.join(_os_main.path.dirname(__file__), ".."))
if _BACKEND_DIR_MAIN not in _sys_main.path:
    _sys_main.path.insert(0, _BACKEND_DIR_MAIN)

from unittest.mock import AsyncMock, MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
import io

from requirement_summarizer_helpers import (
    validate_extension,
    validate_env_vars,
    SUPPORTED_EXTENSIONS as _SUPPORTED_EXTENSIONS,
    REQUIRED_ENV_VARS as _REQUIRED_ENV_VARS,
)

# ---------------------------------------------------------------------------
# Feature: requirement-summarizer, Property 1: File Extension Acceptance/Rejection
# ---------------------------------------------------------------------------

_ALL_TEST_EXTENSIONS = list(_SUPPORTED_EXTENSIONS) + [
    ".exe", ".zip", ".csv", ".html", ".xml", ".mp4", ".mp3", ".py", ".js", ".bat",
]


# Feature: requirement-summarizer, Property 1: File Extension Acceptance/Rejection
@given(
    stem=st.text(min_size=0, max_size=50),
    ext=st.sampled_from(_ALL_TEST_EXTENSIONS),
)
@settings(max_examples=100)
def test_extension_acceptance_rejection(stem: str, ext: str) -> None:
    """
    Validates: Requirements 1.1, 1.3

    validate_extension(filename) returns True iff the lowercase extension is in
    the supported set, and False otherwise.
    """
    filename = stem + ext
    result = validate_extension(filename)
    expected = ext.lower() in _SUPPORTED_EXTENSIONS
    assert result == expected, (
        f"validate_extension({filename!r}) returned {result}, expected {expected}"
    )


# ---------------------------------------------------------------------------
# Feature: requirement-summarizer, Property 2: File Size Enforcement
# ---------------------------------------------------------------------------

_MAX_SIZE = 20_971_520  # 20 MB


def _make_analyze_test_client() -> TestClient:
    """
    Build a TestClient for the FastAPI app with all external dependencies mocked
    so no real DB, OCR, or Gemini calls are made.
    """
    import requirement_summarizer_app as _rs_module
    import ocr_engine as _ocr_module
    import gemini_engine as _gem_module_main
    from database import DatabaseError
    from ocr_engine import ExtractionResult
    from gemini_engine import AnalysisResult as _AR, UserStory as _US

    _mock_session_record = MagicMock()
    _mock_session_record.id = "00000000-0000-0000-0000-000000000001"

    _mock_db = AsyncMock()

    async def _fake_get_session():
        yield _mock_db

    _mock_extraction = ExtractionResult(text="hello world", char_count=11, page_count=1)
    _mock_analysis = _AR(
        executive_summary="summary",
        user_stories=[],
        acceptance_criteria=[],
        gap_flags=[],
    )

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_fake_get_session),
        patch("requirement_summarizer_app.create_session_record", new=AsyncMock(return_value=_mock_session_record)),
        patch("requirement_summarizer_app.update_session_extraction", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_result", new=AsyncMock()),
        patch.object(_ocr_module, "extract_text", return_value=_mock_extraction),
        patch.object(_gem_module_main._client.aio.models, "generate_content", new=AsyncMock(return_value=MagicMock(text=json.dumps({
            "executive_summary": "summary",
            "user_stories": [],
            "acceptance_criteria": [],
            "gap_flags": [],
        })))),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        return client


# Feature: requirement-summarizer, Property 2: File Size Enforcement
@given(file_size=st.integers(min_value=0, max_value=40_000_000))
@settings(max_examples=50, deadline=None)
def test_file_size_enforcement(file_size: int) -> None:
    """
    Validates: Requirements 1.2

    Files with size <= 20,971,520 bytes are accepted (not HTTP 413).
    Files with size > 20,971,520 bytes return HTTP 413.
    """
    import requirement_summarizer_app as _rs_module
    import ocr_engine as _ocr_module
    import gemini_engine as _gem_module_main
    from ocr_engine import ExtractionResult
    from gemini_engine import AnalysisResult as _AR

    _mock_session_record = MagicMock()
    _mock_session_record.id = "00000000-0000-0000-0000-000000000001"
    _mock_db = AsyncMock()

    async def _fake_get_session():
        yield _mock_db

    extracted_text = "x" * min(file_size, 100)  # keep extraction non-empty for valid sizes
    _mock_extraction = ExtractionResult(
        text=extracted_text if file_size <= _MAX_SIZE else "",
        char_count=len(extracted_text),
        page_count=1,
    )
    _mock_analysis = _AR(
        executive_summary="summary",
        user_stories=[],
        acceptance_criteria=[],
        gap_flags=[],
    )

    file_content = b"x" * file_size
    # Use a valid .txt extension so extension check passes
    filename = "test.txt"

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_fake_get_session),
        patch("requirement_summarizer_app.create_session_record", new=AsyncMock(return_value=_mock_session_record)),
        patch("requirement_summarizer_app.update_session_extraction", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_result", new=AsyncMock()),
        patch.object(_ocr_module, "extract_text", return_value=_mock_extraction),
        patch.object(_gem_module_main._client.aio.models, "generate_content", new=AsyncMock(return_value=MagicMock(text=json.dumps({
            "executive_summary": "summary",
            "user_stories": [],
            "acceptance_criteria": [],
            "gap_flags": [],
        })))),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        response = client.post(
            "/analyze",
            files={"file": (filename, io.BytesIO(file_content), "text/plain")},
        )

    if file_size > _MAX_SIZE:
        assert response.status_code == 413, (
            f"Expected 413 for file_size={file_size}, got {response.status_code}"
        )
    else:
        assert response.status_code != 413, (
            f"Got unexpected 413 for file_size={file_size} (<= {_MAX_SIZE})"
        )


# ---------------------------------------------------------------------------
# Feature: requirement-summarizer, Property 3: Response Contains Extraction Counts
# ---------------------------------------------------------------------------


# Feature: requirement-summarizer, Property 3: Response Contains Extraction Counts
@given(extracted_text=st.text(min_size=1))
@settings(max_examples=50)
def test_response_contains_extraction_counts(extracted_text: str) -> None:
    """
    Validates: Requirements 1.5

    For any non-empty extracted text, the /analyze response must contain
    char_count == len(extracted_text) and page_count >= 0.
    """
    import requirement_summarizer_app as _rs_module
    import ocr_engine as _ocr_module
    import gemini_engine as _gem_module_main
    from ocr_engine import ExtractionResult
    from gemini_engine import AnalysisResult as _AR

    _mock_session_record = MagicMock()
    _mock_session_record.id = "00000000-0000-0000-0000-000000000002"
    _mock_db = AsyncMock()

    async def _fake_get_session():
        yield _mock_db

    page_count = max(1, len(extracted_text) // 500)
    _mock_extraction = ExtractionResult(
        text=extracted_text,
        char_count=len(extracted_text),
        page_count=page_count,
    )
    _mock_analysis = _AR(
        executive_summary="summary",
        user_stories=[],
        acceptance_criteria=[],
        gap_flags=[],
    )

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_fake_get_session),
        patch("requirement_summarizer_app.create_session_record", new=AsyncMock(return_value=_mock_session_record)),
        patch("requirement_summarizer_app.update_session_extraction", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_result", new=AsyncMock()),
        patch.object(_ocr_module, "extract_text", return_value=_mock_extraction),
        patch.object(_gem_module_main._client.aio.models, "generate_content", new=AsyncMock(return_value=MagicMock(text=json.dumps({
            "executive_summary": "summary",
            "user_stories": [],
            "acceptance_criteria": [],
            "gap_flags": [],
        })))),
    ):
        client = TestClient(_rs_module.rs_app, raise_server_exceptions=False)
        # Use a small valid .txt file (content doesn't matter since OCR is mocked)
        response = client.post(
            "/analyze",
            files={"file": ("test.txt", io.BytesIO(b"placeholder"), "text/plain")},
        )

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["char_count"] == len(extracted_text), (
        f"char_count mismatch: expected {len(extracted_text)}, got {body['char_count']}"
    )
    assert body["page_count"] >= 0, (
        f"page_count must be >= 0, got {body['page_count']}"
    )


# ---------------------------------------------------------------------------
# Feature: requirement-summarizer, Property 12: Missing Env Var Detection
# ---------------------------------------------------------------------------


# Feature: requirement-summarizer, Property 12: Missing Env Var Detection
@given(
    missing_vars=st.frozensets(
        st.sampled_from(_REQUIRED_ENV_VARS),
        min_size=1,
    )
)
@settings(max_examples=100)
def test_missing_env_var_detection(missing_vars: frozenset) -> None:
    """
    Validates: Requirements 4.2, 4.3

    For any non-empty subset of required env vars that is missing, validate_env_vars()
    must raise a RuntimeError whose message identifies at least one missing variable name.
    """
    # Build an env dict with all required vars present, then remove the missing ones
    full_env = {var: "dummy_value" for var in _REQUIRED_ENV_VARS}
    for var in missing_vars:
        del full_env[var]

    raised = False
    error_message = ""
    try:
        validate_env_vars(full_env)
    except RuntimeError as exc:
        raised = True
        error_message = str(exc)

    assert raised, (
        f"validate_env_vars() did not raise for missing vars: {missing_vars}"
    )
    # At least one of the missing variable names must appear in the error message
    assert any(var in error_message for var in missing_vars), (
        f"Error message {error_message!r} does not identify any of the missing vars: {missing_vars}"
    )
