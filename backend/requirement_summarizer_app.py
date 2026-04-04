"""
Requirement Summarizer — standalone FastAPI application.

Exposes:
  GET  /health   → {"status": "ok"}
  POST /analyze  → AnalyzeResponse

All external dependencies (DB, OCR, Gemini) are imported lazily inside the
endpoint so this module can be imported in tests without triggering real
service initialization.
"""

from __future__ import annotations

import base64
import dataclasses
import time
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.requests import Request

from logging_config import get_logger
from rate_limiter import limiter
from requirement_summarizer_helpers import (
    MAX_FILE_SIZE as _MAX_FILE_SIZE,
    validate_extension,
    validate_env_vars,
)

# Import DB functions at module level so they can be patched in tests
from database import (
    DatabaseError,
    create_session_record,
    get_db_context,
    get_history,
    get_session,
    log_audit_event,
    save_document_metadata,
    save_analysis_result,
    update_document_status,
    update_session_extraction,
    update_session_result,
)
from models import AuditLog

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level startup time for uptime reporting (Req 9.8)
# ---------------------------------------------------------------------------

APP_START_TIME = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Voice audit helper
# ---------------------------------------------------------------------------

async def _write_voice_audit(db_factory, endpoint: str, voice: str, duration_ms: int) -> None:
    """Fire-and-forget background task: write a voice_generated AuditLog entry."""
    try:
        async with db_factory() as db:
            await log_audit_event(db, action="voice_generated", details={
                "endpoint": endpoint,
                "voice": voice,
                "duration_ms": duration_ms,
            })
    except Exception:
        pass  # fire-and-forget — never propagate


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate env vars and initialize DB on startup."""
    try:
        validate_env_vars()
    except RuntimeError as exc:
        logger.warning("env_vars_missing_at_startup", error=str(exc))
    from database import init_db
    try:
        await init_db()
    except Exception as exc:
        logger.warning("db_init_failed_at_startup", error=str(exc))
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

rs_app = FastAPI(lifespan=lifespan)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

ALLOWED_ORIGINS = [
    "https://sayan1320.github.io",
    "http://localhost:5173",
    "http://localhost:3000",
]

rs_app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

VoiceName = Literal["Aoede", "Charon", "Fenrir", "Kore", "Puck"]


class UserStoryRequest(BaseModel):
    id: str
    role: str
    feature: str
    benefit: str
    priority: str


class AnalysisSummaryRequest(BaseModel):
    executive_summary: str
    user_stories: list = []
    acceptance_criteria: list = []
    gap_flags: list = []


class VoiceStoryRequest(BaseModel):
    story: UserStoryRequest
    voice: VoiceName


class AudioResponse(BaseModel):
    audio: str  # base64-encoded WAV


class AnalyzeResponse(BaseModel):
    session_id: str
    document_id: str
    filename: str
    char_count: int
    page_count: int
    analysis: dict
    request_id: str
    db_persisted: bool


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@rs_app.get("/health")
async def health() -> dict:
    """Enhanced health check — returns component status and uptime."""
    import os
    import asyncio
    from sqlalchemy import text

    # DB check with 3-second timeout
    db_status = "error"
    db_gen = get_session()
    try:
        db = await db_gen.__anext__()
        await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=3.0)
        db_status = "ok"
    except Exception:
        db_status = "error"
    finally:
        try:
            await db_gen.aclose()
        except Exception:
            pass

    components = {
        "database": db_status,
        "gemini_api": "ok" if os.getenv("GOOGLE_AI_API_KEY") else "error",
        "llamaparse_api": "ok" if os.getenv("LLAMA_CLOUD_API_KEY") else "error",
    }
    overall = "ok" if all(v == "ok" for v in components.values()) else "degraded"
    uptime = int((datetime.now(timezone.utc) - APP_START_TIME).total_seconds())

    return JSONResponse(status_code=200, content={
        "status": overall,
        "service": "ai-req-summarizer",
        "version": "2.0",
        "components": components,
        "uptime_seconds": uptime,
    })


# ---------------------------------------------------------------------------
# GET /demo/sample-text  (Req 10.2)
# ---------------------------------------------------------------------------

@rs_app.get("/demo/sample-text")
async def get_sample_text():
    fixture_path = Path(__file__).parent / "tests/fixtures/sample_requirement.txt"
    text = fixture_path.read_text(encoding="utf-8")
    return {"text": text, "filename": "sample_brd.txt", "file_type": "txt"}


# ---------------------------------------------------------------------------
# POST /demo/analyze  (Req 10.3)
# ---------------------------------------------------------------------------

@rs_app.post("/demo/analyze")
@limiter.limit("20/minute")
async def demo_analyze(request: Request):
    import json
    demo_path = Path(__file__).parent / "demo_result.json"
    return JSONResponse(json.loads(demo_path.read_text()))


# ---------------------------------------------------------------------------
# GET /history
# ---------------------------------------------------------------------------

@rs_app.get("/history")
async def get_history_endpoint(limit: int = 10) -> dict:
    """
    Return recent analysis history records.
    limit must be between 1 and 50 (inclusive).
    """
    if limit < 1 or limit > 50:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 50")

    db_gen = get_session()
    try:
        db = await db_gen.__anext__()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable. Please try again later.",
        )

    try:
        records = await get_history(db, limit)
        return {"history": records, "count": len(records)}
    finally:
        try:
            await db_gen.aclose()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# POST /analyze
# ---------------------------------------------------------------------------

@rs_app.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit("5/minute")
async def analyze_document(request: Request, file: UploadFile = File(...)) -> AnalyzeResponse:
    """
    Accept a multipart/form-data upload, extract text via OCR, analyze with
    Gemini, persist results in AlloyDB, and return structured analysis.
    """
    import ocr_engine
    import gemini_engine

    request_id = str(uuid4())
    log = get_logger("analyze").bind(request_id=request_id)
    t_start = time.monotonic()

    filename = file.filename or "upload"

    # 1. Validate file extension
    if not validate_extension(filename):
        raise HTTPException(
            status_code=415,
            detail=(
                "Unsupported file type. "
                "Supported: .pdf, .docx, .txt, .png, .jpg, .jpeg, .tiff"
            ),
        )

    # 2. Read file bytes and validate size
    file_bytes = await file.read()
    if len(file_bytes) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File too large. Maximum size is 20 MB.",
        )

    file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    file_size_kb = len(file_bytes) // 1024

    log.info("analyze_start", filename=filename, file_type=file_type, file_size_kb=file_size_kb)

    # 3. DB circuit breaker: try to get session and create session record.
    # If DB is down, continue without a session — db_persisted stays False.
    db_persisted = False
    db_gen = None
    db = None
    session_id = "unavailable"
    document_id = "unavailable"
    doc = None

    try:
        db_gen = get_session()
        db = await db_gen.__anext__()
        session_record = await create_session_record(db, filename, len(file_bytes))
        session_id = str(session_record.id)

        # 4. Save document metadata (non-fatal)
        try:
            doc = await save_document_metadata(
                db,
                session_id=session_record.id,
                filename=filename,
                file_type=file_type,
                file_size_kb=file_size_kb,
                page_count=0,
            )
            db.add(AuditLog(session_id=session_record.id, event_type="document_uploaded"))
            await db.flush()
        except Exception as exc:
            log.error("db_degraded", error_type=type(exc).__name__)

    except Exception as exc:
        log.error("db_degraded", error_type=type(exc).__name__)

    # 5. OCR extraction — still raises HTTP 502 on failure
    t_ocr = time.monotonic()
    try:
        extraction = ocr_engine.extract_text(file_bytes, filename)
    except Exception as exc:
        duration_ms = int((time.monotonic() - t_start) * 1000)
        log.error("analyze_failure", error_type=type(exc).__name__, error_message=str(exc), duration_ms=duration_ms)
        raise HTTPException(
            status_code=502,
            detail=f"OCR extraction failed: {exc}",
        )

    ocr_duration_ms = int((time.monotonic() - t_ocr) * 1000)
    log.info("ocr_complete", page_count=extraction.page_count, char_count=extraction.char_count, duration_ms=ocr_duration_ms)

    if not extraction.text:
        duration_ms = int((time.monotonic() - t_start) * 1000)
        log.error("analyze_failure", error_type="EmptyExtractionError", error_message="No text could be extracted from the uploaded file.", duration_ms=duration_ms)
        raise HTTPException(
            status_code=422,
            detail="No text could be extracted from the uploaded file.",
        )

    # 6. Update session with extraction counts (non-fatal)
    if db is not None and session_id != "unavailable":
        try:
            await update_session_extraction(
                db, session_record.id, extraction.char_count, extraction.page_count
            )
        except Exception:
            pass

    # 7. Gemini analysis — still raises HTTP 502 on failure
    t_gemini = time.monotonic()
    try:
        analysis_result = await gemini_engine.analyze(extraction.text)
    except Exception as exc:
        duration_ms = int((time.monotonic() - t_start) * 1000)
        log.error("analyze_failure", error_type=type(exc).__name__, error_message=str(exc), duration_ms=duration_ms)
        # Best-effort: mark document as failed in DB
        if db is not None and doc is not None:
            try:
                await update_document_status(db, doc.id, "failed")
                db.add(AuditLog(session_id=session_record.id, event_type="analysis_failed"))
                await db.commit()
            except Exception:
                pass
        raise HTTPException(
            status_code=502,
            detail=f"AI analysis failed: {exc}",
        )

    gemini_duration_ms = int((time.monotonic() - t_gemini) * 1000)
    log.info("gemini_complete", tokens_used=0, model_used="gemini", duration_ms=gemini_duration_ms)

    analysis_dict = dataclasses.asdict(analysis_result)

    # 8. Persist analysis result to DB (circuit breaker — non-fatal)
    try:
        if db is not None and session_id != "unavailable":
            if doc is not None:
                await save_analysis_result(
                    db,
                    document_id=doc.id,
                    session_id=session_record.id,
                    result_dict=analysis_dict,
                    tokens_used=0,
                    processing_time_ms=0,
                    model_used="gemini",
                )
                document_id = str(doc.id)

            # 9. Update legacy session result (non-fatal)
            try:
                await update_session_result(db, session_record.id, analysis_result)
            except Exception as exc:
                logger.error(
                    "db.update_session_result.failed",
                    session_id=session_id,
                    error=str(exc),
                )

            if doc is not None:
                await update_document_status(db, doc.id, "completed")
            db.add(AuditLog(session_id=session_record.id, event_type="analysis_complete"))
            await db.commit()

            db_persisted = True
            total_duration_ms = int((time.monotonic() - t_start) * 1000)
            log.info("analyze_success", document_id=document_id, total_duration_ms=total_duration_ms)
    except Exception as exc:
        log.error("db_degraded", error_type=type(exc).__name__)
        db_persisted = False
    finally:
        if db_gen is not None:
            try:
                await db_gen.aclose()
            except Exception:
                pass

    # 10. Build and return response — always succeeds regardless of DB outcome
    return AnalyzeResponse(
        session_id=session_id,
        document_id=document_id,
        filename=filename,
        char_count=extraction.char_count,
        page_count=extraction.page_count,
        analysis=analysis_dict,
        request_id=request_id,
        db_persisted=db_persisted,
    )


# ---------------------------------------------------------------------------
# POST /voice-summary
# ---------------------------------------------------------------------------

@rs_app.post("/voice-summary", response_model=AudioResponse)
@limiter.limit("10/minute")
async def voice_summary(request: Request, req: AnalysisSummaryRequest, background_tasks: BackgroundTasks) -> AudioResponse:
    import voice_engine
    try:
        voice_engine.check_api_key()
        t0 = time.monotonic()
        wav_bytes = await voice_engine.summarize_to_speech(req.model_dump())
        duration_ms = int((time.monotonic() - t0) * 1000)
    except voice_engine.TTSConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except voice_engine.TTSError as exc:
        raise HTTPException(status_code=502, detail=f"TTS synthesis failed: {exc}")
    background_tasks.add_task(_write_voice_audit, get_db_context, "/voice-summary", "default", duration_ms)
    return AudioResponse(audio=base64.b64encode(wav_bytes).decode())


# ---------------------------------------------------------------------------
# POST /voice-story
# ---------------------------------------------------------------------------

@rs_app.post("/voice-story", response_model=AudioResponse)
@limiter.limit("10/minute")
async def voice_story(request: Request, req: VoiceStoryRequest, background_tasks: BackgroundTasks) -> AudioResponse:
    import voice_engine
    text = voice_engine.format_story_narration(req.story.model_dump())
    try:
        t0 = time.monotonic()
        wav_bytes = await voice_engine.text_to_speech_custom(text, req.voice, endpoint="/voice-story")
        duration_ms = int((time.monotonic() - t0) * 1000)
    except voice_engine.TTSError as exc:
        raise HTTPException(status_code=502, detail=f"TTS synthesis failed: {exc}")
    background_tasks.add_task(_write_voice_audit, get_db_context, "/voice-story", req.voice, duration_ms)
    return AudioResponse(audio=base64.b64encode(wav_bytes).decode())
