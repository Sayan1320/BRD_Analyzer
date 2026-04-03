"""
Async AlloyDB database layer for the Requirement Summarizer service.

Uses SQLAlchemy async engine with the AlloyDB Cloud Connector (asyncpg dialect).
All DB errors are caught, logged with structlog (sanitized), and re-raised as DatabaseError.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from models import AnalysisResult, AuditLog, Base, DocumentMetadata, Session

logger = structlog.get_logger(__name__)

# Module-level engine and session factory (initialized by init_db)
_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


class DatabaseError(Exception):
    """Raised when a database operation fails."""


def sanitize_error_message(message: str, sensitive_strings: list[str]) -> str:
    """
    Remove any sensitive substrings (connection strings, passwords, etc.)
    from an error message before logging or returning it to callers.
    """
    sanitized = message
    for sensitive in sensitive_strings:
        if sensitive:
            sanitized = sanitized.replace(sensitive, "[REDACTED]")
    return sanitized


def _get_sensitive_strings() -> list[str]:
    """Collect env-var values that must never appear in logs or responses."""
    sensitive = []
    for var in ("ALLOYDB_INSTANCE_URI", "DB_PASS", "DB_USER", "DB_NAME"):
        val = os.environ.get(var)
        if val:
            sensitive.append(val)
    return sensitive


async def init_db() -> None:
    """
    Initialize the async SQLAlchemy engine using the AlloyDB Cloud Connector
    and create all ORM tables if they do not already exist.
    """
    global _engine, _async_session_factory

    instance_uri = os.environ["ALLOYDB_INSTANCE_URI"]
    db_user = os.environ["DB_USER"]
    db_pass = os.environ["DB_PASS"]
    db_name = os.environ["DB_NAME"]

    try:
        from google.cloud.alloydb.connector import AsyncConnector  # type: ignore

        connector = await AsyncConnector.create()

        async def _getconn():  # type: ignore
            return await connector.connect(
                instance_uri,
                "asyncpg",
                user=db_user,
                password=db_pass,
                db=db_name,
            )

        _engine = create_async_engine(
            "postgresql+asyncpg://",
            async_creator=_getconn,
            echo=False,
        )
    except Exception as exc:
        sensitive = _get_sensitive_strings()
        safe_msg = sanitize_error_message(str(exc), sensitive)
        logger.error("database.init_db.failed", error=safe_msg)
        raise DatabaseError(f"Failed to initialize database: {safe_msg}") from exc

    _async_session_factory = async_sessionmaker(
        _engine, class_=AsyncSession, expire_on_commit=False
    )

    try:
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        sensitive = _get_sensitive_strings()
        safe_msg = sanitize_error_message(str(exc), sensitive)
        logger.error("database.create_tables.failed", error=safe_msg)
        raise DatabaseError(f"Failed to create tables: {safe_msg}") from exc


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async generator that yields an AsyncSession for use as a FastAPI dependency.
    """
    if _async_session_factory is None:
        raise DatabaseError("Database not initialized. Call init_db() first.")

    async with _async_session_factory() as session:
        try:
            yield session
        except Exception as exc:
            await session.rollback()
            sensitive = _get_sensitive_strings()
            safe_msg = sanitize_error_message(str(exc), sensitive)
            logger.error("database.session.error", error=safe_msg)
            raise DatabaseError(f"Session error: {safe_msg}") from exc


async def create_session_record(
    db: AsyncSession,
    filename: str,
    file_size_bytes: int,
) -> Session:
    """
    Insert a new Session row with status='processing' and an AuditLog entry
    with event_type='upload'. Returns the created Session.
    """
    try:
        session_obj = Session(
            filename=filename,
            file_size_bytes=file_size_bytes,
            status="processing",
        )
        db.add(session_obj)
        await db.flush()  # populate session_obj.id

        audit = AuditLog(
            session_id=session_obj.id,
            event_type="upload",
        )
        db.add(audit)
        await db.commit()
        await db.refresh(session_obj)
        return session_obj
    except Exception as exc:
        await db.rollback()
        sensitive = _get_sensitive_strings()
        safe_msg = sanitize_error_message(str(exc), sensitive)
        logger.error(
            "database.create_session_record.failed",
            filename=filename,
            error=safe_msg,
        )
        raise DatabaseError(f"Failed to create session record: {safe_msg}") from exc


async def update_session_extraction(
    db: AsyncSession,
    session_id: uuid.UUID,
    char_count: int,
    page_count: int,
) -> None:
    """
    Update the Session row identified by session_id with char_count and page_count.
    """
    try:
        stmt = (
            update(Session)
            .where(Session.id == session_id)
            .values(char_count=char_count, page_count=page_count)
        )
        await db.execute(stmt)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        sensitive = _get_sensitive_strings()
        safe_msg = sanitize_error_message(str(exc), sensitive)
        logger.error(
            "database.update_session_extraction.failed",
            session_id=str(session_id),
            error=safe_msg,
        )
        raise DatabaseError(f"Failed to update session extraction: {safe_msg}") from exc


async def update_session_result(
    db: AsyncSession,
    session_id: uuid.UUID,
    result: Any,
) -> None:
    """
    Save the analysis result (as a dict/JSONB) to the Session row, set status='complete',
    and insert an AuditLog entry with event_type='analysis_complete'.
    """
    try:
        # Serialize result to dict if it has a to_dict / asdict method
        if hasattr(result, "__dataclass_fields__"):
            import dataclasses
            result_dict = dataclasses.asdict(result)
        elif isinstance(result, dict):
            result_dict = result
        else:
            result_dict = dict(result)

        stmt = (
            update(Session)
            .where(Session.id == session_id)
            .values(result=result_dict, status="complete")
        )
        await db.execute(stmt)

        audit = AuditLog(
            session_id=session_id,
            event_type="analysis_complete",
        )
        db.add(audit)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        sensitive = _get_sensitive_strings()
        safe_msg = sanitize_error_message(str(exc), sensitive)
        logger.error(
            "database.update_session_result.failed",
            session_id=str(session_id),
            error=safe_msg,
        )
        raise DatabaseError(f"Failed to update session result: {safe_msg}") from exc


async def save_document_metadata(
    db: AsyncSession,
    session_id: uuid.UUID,
    filename: str,
    file_type: str,
    file_size_kb: int,
    page_count: int,
) -> DocumentMetadata:
    """
    Create a DocumentMetadata record with status='processing', flush (no commit).
    Returns the DocumentMetadata instance.
    """
    doc = DocumentMetadata(
        session_id=session_id,
        filename=filename,
        file_type=file_type,
        file_size_kb=file_size_kb,
        page_count=page_count,
        status="processing",
    )
    db.add(doc)
    await db.flush()
    return doc


async def save_analysis_result(
    db: AsyncSession,
    document_id: uuid.UUID,
    session_id: uuid.UUID,
    result_dict: dict,
    tokens_used: int,
    processing_time_ms: int,
    model_used: str,
) -> AnalysisResult:
    """
    Create an AnalysisResult record from result_dict, flush (no commit).
    Returns the AnalysisResult instance.
    """
    result = AnalysisResult(
        document_id=document_id,
        session_id=session_id,
        executive_summary=result_dict.get("executive_summary"),
        user_stories=result_dict.get("user_stories"),
        acceptance_criteria=result_dict.get("acceptance_criteria"),
        gap_flags=result_dict.get("gap_flags"),
        tokens_used=tokens_used,
        processing_time_ms=processing_time_ms,
        model_used=model_used,
    )
    db.add(result)
    await db.flush()
    return result


_VALID_STATUSES = {"processing", "completed", "failed"}


async def update_document_status(
    db: AsyncSession,
    document_id: uuid.UUID,
    status: str,
) -> None:
    """
    Update the status of a DocumentMetadata record.
    Raises ValueError for invalid status values.
    """
    if status not in _VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Must be one of: {sorted(_VALID_STATUSES)}"
        )
    stmt = (
        update(DocumentMetadata)
        .where(DocumentMetadata.id == document_id)
        .values(status=status)
    )
    await db.execute(stmt)


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager that yields an AsyncSession.
    Intended for fire-and-forget background tasks that need a DB session.
    """
    if _async_session_factory is None:
        raise DatabaseError("Database not initialized. Call init_db() first.")

    async with _async_session_factory() as session:
        try:
            yield session
        except Exception as exc:
            await session.rollback()
            raise


async def log_audit_event(
    db: AsyncSession,
    action: str,
    details: dict | None = None,
) -> None:
    """
    Write a generic audit event. Uses the AuditLog model's action/details fields
    if available, otherwise falls back to event_type. Commits the session.
    """
    try:
        # AuditLog currently uses event_type; store action there and details in a
        # separate column if it exists, otherwise encode into event_type.
        audit = AuditLog(
            session_id=uuid.uuid4(),  # standalone audit — no session context
            event_type=action,
        )
        # Attach details as a dynamic attribute if the model supports it
        if details is not None and hasattr(AuditLog, "details"):
            audit.details = details  # type: ignore[attr-defined]
        db.add(audit)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        sensitive = _get_sensitive_strings()
        safe_msg = sanitize_error_message(str(exc), sensitive)
        logger.error("database.log_audit_event.failed", action=action, error=safe_msg)
        raise DatabaseError(f"Failed to log audit event: {safe_msg}") from exc


async def get_metrics_summary(db: AsyncSession) -> dict:
    """
    Return a 24-hour summary of key metrics from the database.
    Returns zeros on empty DB or any DB error.
    """
    default = {
        "total_analyses": 0,
        "avg_tokens": 0,
        "avg_processing_ms": 0,
        "total_voice_requests": 0,
        "error_count": 0,
        "model_breakdown": {},
    }
    try:
        # 1. Total analyses in last 24h
        row = (await db.execute(text(
            "SELECT COUNT(*) FROM analysis_results "
            "WHERE created_at > NOW() - INTERVAL '24 hours'"
        ))).scalar()
        total_analyses = int(row or 0)

        # 2. Avg tokens in last 24h
        row = (await db.execute(text(
            "SELECT AVG(tokens_used) FROM analysis_results "
            "WHERE created_at > NOW() - INTERVAL '24 hours'"
        ))).scalar()
        avg_tokens = int(row or 0)

        # 3. Avg processing time in last 24h
        row = (await db.execute(text(
            "SELECT AVG(processing_time_ms) FROM analysis_results "
            "WHERE created_at > NOW() - INTERVAL '24 hours'"
        ))).scalar()
        avg_processing_ms = int(row or 0)

        # 4. Voice requests in last 24h
        row = (await db.execute(text(
            "SELECT COUNT(*) FROM audit_log "
            "WHERE action = 'voice_generated' "
            "AND created_at > NOW() - INTERVAL '24 hours'"
        ))).scalar()
        total_voice_requests = int(row or 0)

        # 5. Failed documents
        row = (await db.execute(text(
            "SELECT COUNT(*) FROM document_metadata WHERE status = 'failed'"
        ))).scalar()
        error_count = int(row or 0)

        # 6. Model breakdown in last 24h
        rows = (await db.execute(text(
            "SELECT model_used, COUNT(*) as cnt FROM analysis_results "
            "WHERE created_at > NOW() - INTERVAL '24 hours' "
            "GROUP BY model_used"
        ))).all()
        model_breakdown = {r[0]: int(r[1]) for r in rows if r[0] is not None}

        return {
            "total_analyses": total_analyses,
            "avg_tokens": avg_tokens,
            "avg_processing_ms": avg_processing_ms,
            "total_voice_requests": total_voice_requests,
            "error_count": error_count,
            "model_breakdown": model_breakdown,
        }
    except Exception as exc:
        sensitive = _get_sensitive_strings()
        safe_msg = sanitize_error_message(str(exc), sensitive)
        logger.error("database.get_metrics_summary.failed", error=safe_msg)
        return default


async def get_history(db: AsyncSession, limit: int = 10) -> list[dict]:
    """
    Return recent analysis records joined with document metadata, ordered by
    created_at DESC. Limit is clamped to a maximum of 50. Returns empty list
    when no records exist (never raises).
    """
    limit = min(limit, 50)
    try:
        stmt = (
            select(
                AnalysisResult.id.label("document_id"),
                DocumentMetadata.filename,
                DocumentMetadata.file_type,
                AnalysisResult.model_used,
                AnalysisResult.tokens_used,
                AnalysisResult.processing_time_ms,
                AnalysisResult.created_at,
            )
            .join(DocumentMetadata, AnalysisResult.document_id == DocumentMetadata.id)
            .order_by(AnalysisResult.created_at.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()
        return [
            {
                "document_id": str(row.document_id),
                "filename": row.filename,
                "file_type": row.file_type,
                "model_used": row.model_used,
                "tokens_used": row.tokens_used,
                "processing_time_ms": row.processing_time_ms,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    except Exception as exc:
        sensitive = _get_sensitive_strings()
        safe_msg = sanitize_error_message(str(exc), sensitive)
        logger.error("database.get_history.failed", error=safe_msg)
        return []
