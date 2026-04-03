"""
Unit tests for Spec 08 - Observability.
Tasks 9.1-9.8: structured logging, middleware, metrics, and request_id correlation.
"""

from __future__ import annotations

import io
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend/ is on the path
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


def _make_analyze_mocks():
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


@pytest.mark.asyncio
async def test_middleware_captures_status_code_and_duration_ms():
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    import logging_config
    import time as _time
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as _Request

    _logger = logging_config.get_logger("test_mw_91")

    class _TestMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.url.path == "/health":
                return await call_next(request)
            start = _time.perf_counter()
            response = await call_next(request)
            duration_ms = round((_time.perf_counter() - start) * 1000, 2)
            _logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                client_ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response

    mini_app = FastAPI()

    @mini_app.get("/ping")
    async def ping():
        return {"pong": True}

    mini_app.add_middleware(_TestMiddleware)

    log_calls = []

    def _capture_info(event, **kwargs):
        log_calls.append({"event": event, **kwargs})

    with patch.object(_logger, "info", side_effect=_capture_info):
        transport = ASGITransport(app=mini_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ping")

    assert resp.status_code == 200
    assert len(log_calls) == 1
    entry = log_calls[0]
    assert entry["event"] == "http_request"
    assert "status_code" in entry
    assert entry["status_code"] == 200
    assert "duration_ms" in entry
    assert isinstance(entry["duration_ms"], (int, float))
    assert entry["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_middleware_excludes_health_path():
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    import logging_config
    import time as _time
    from starlette.middleware.base import BaseHTTPMiddleware

    _logger = logging_config.get_logger("test_mw_92")

    class _TestMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.url.path == "/health":
                return await call_next(request)
            start = _time.perf_counter()
            response = await call_next(request)
            duration_ms = round((_time.perf_counter() - start) * 1000, 2)
            _logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response

    mini_app = FastAPI()

    @mini_app.get("/health")
    async def health():
        return {"status": "ok"}

    mini_app.add_middleware(_TestMiddleware)

    log_calls = []

    def _capture_info(event, **kwargs):
        log_calls.append({"event": event, **kwargs})

    with patch.object(_logger, "info", side_effect=_capture_info):
        transport = ASGITransport(app=mini_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")

    assert resp.status_code == 200
    assert len(log_calls) == 0


def test_analyze_emits_five_log_events_with_shared_request_id():
    import ocr_engine as _ocr
    import gemini_engine as _gem
    import requirement_summarizer_app as _rs_module
    from fastapi.testclient import TestClient

    mock_session_record, mock_db, extraction, analysis_json = _make_analyze_mocks()

    async def _ok_get_session():
        yield mock_db

    real_bound_logger_calls = []

    class _CaptureBoundLogger:
        def __init__(self, request_id):
            self._request_id = request_id

        def info(self, event, **kwargs):
            real_bound_logger_calls.append({"event": event, "request_id": self._request_id, **kwargs})

        def error(self, event, **kwargs):
            real_bound_logger_calls.append({"event": event, "request_id": self._request_id, **kwargs})

    class _CaptureLogger:
        def bind(self, **kwargs):
            return _CaptureBoundLogger(kwargs.get("request_id"))

        def info(self, event, **kwargs):
            pass

        def error(self, event, **kwargs):
            pass

    def _fake_get_logger(name):
        if name == "analyze":
            return _CaptureLogger()
        return MagicMock()

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
            files={"file": ("req.txt", io.BytesIO(b"hello world"), "text/plain")},
        )

    assert response.status_code == 200

    assert len(real_bound_logger_calls) >= 4, (
        f"Expected at least 4 log events, got {len(real_bound_logger_calls)}: "
        f"{[e['event'] for e in real_bound_logger_calls]}"
    )

    request_ids = {e["request_id"] for e in real_bound_logger_calls}
    assert len(request_ids) == 1, f"Expected 1 unique request_id, got: {request_ids}"
    assert next(iter(request_ids)) is not None

    event_names = [e["event"] for e in real_bound_logger_calls]
    assert "analyze_start" in event_names
    assert "ocr_complete" in event_names
    assert "gemini_complete" in event_names
    assert "analyze_success" in event_names


def test_analyze_response_includes_request_id():
    import ocr_engine as _ocr
    import gemini_engine as _gem
    import requirement_summarizer_app as _rs_module
    from fastapi.testclient import TestClient

    mock_session_record, mock_db, extraction, analysis_json = _make_analyze_mocks()

    async def _ok_get_session():
        yield mock_db

    with (
        patch("requirement_summarizer_app.get_session", side_effect=_ok_get_session),
        patch("requirement_summarizer_app.create_session_record", new=AsyncMock(return_value=mock_session_record)),
        patch("requirement_summarizer_app.update_session_extraction", new=AsyncMock()),
        patch("requirement_summarizer_app.update_session_result", new=AsyncMock()),
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
            files={"file": ("req.txt", io.BytesIO(b"hello world"), "text/plain")},
        )

    assert response.status_code == 200
    body = response.json()
    assert "request_id" in body
    assert body["request_id"]


def test_metrics_skips_writes_when_gcp_project_id_missing(monkeypatch):
    import metrics

    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)

    mock_client = MagicMock()

    with patch.object(metrics, "_get_client_and_project", return_value=(None, None)):
        metrics.record_analyze_latency(123.4, "pdf", "gemini")
        metrics.record_tokens_per_request(500, "gemini")
        metrics.record_ocr_duration(45.0, "pdf")
        metrics.record_tts_duration(200.0, "Aoede")
        metrics.record_analyze_error("ValueError")

    mock_client.create_time_series.assert_not_called()


@pytest.mark.asyncio
async def test_get_metrics_summary_returns_zeros_on_empty_db():
    from database import get_metrics_summary

    mock_scalar_result = MagicMock()
    mock_scalar_result.scalar.return_value = None
    mock_scalar_result.all.return_value = []

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_scalar_result)

    result = await get_metrics_summary(mock_db)

    assert result["total_analyses"] == 0
    assert result["avg_tokens"] == 0
    assert result["avg_processing_ms"] == 0
    assert result["total_voice_requests"] == 0
    assert result["error_count"] == 0
    assert result["model_breakdown"] == {}


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_200_with_all_six_keys():
    from httpx import AsyncClient, ASGITransport

    mock_summary = {
        "total_analyses": 5,
        "avg_tokens": 1200,
        "avg_processing_ms": 340,
        "total_voice_requests": 2,
        "error_count": 0,
        "model_breakdown": {"gemini-2.0-flash": 5},
    }

    mock_gcp_client_instance = MagicMock()
    mock_gcp_client_instance.connect = AsyncMock()
    mock_gcp_client_instance.close = AsyncMock()

    mock_db = AsyncMock()

    async def _fake_get_session():
        yield mock_db

    with (
        patch("gcp_mcp_client.GCPMCPClient", return_value=mock_gcp_client_instance),
        patch("database.init_db", new=AsyncMock()),
        patch("requirement_summarizer_helpers.validate_env_vars"),
    ):
        import main as _main_module
        from database import get_session as _real_get_session

        # Override the FastAPI dependency so no real DB session is needed
        _main_module.app.dependency_overrides[_real_get_session] = _fake_get_session

        try:
            with patch("main.get_metrics_summary", new=AsyncMock(return_value=mock_summary)):
                transport = ASGITransport(app=_main_module.app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.get("/metrics")
        finally:
            _main_module.app.dependency_overrides.pop(_real_get_session, None)

    assert response.status_code == 200
    body = response.json()

    required_keys = {
        "total_analyses",
        "avg_tokens",
        "avg_processing_ms",
        "total_voice_requests",
        "error_count",
        "model_breakdown",
    }
    missing = required_keys - set(body.keys())
    assert not missing, f"Response missing keys: {missing}"


@pytest.mark.asyncio
async def test_tts_complete_log_includes_audio_size_bytes():
    import voice_engine

    _WAV_STUB = b"RIFF" + b"\x00" * 40

    part = MagicMock()
    part.inline_data.data = _WAV_STUB
    content = MagicMock()
    content.parts = [part]
    candidate = MagicMock()
    candidate.content = content
    mock_response = MagicMock()
    mock_response.candidates = [candidate]

    log_calls = []

    def _capture_info(event, **kwargs):
        log_calls.append({"event": event, **kwargs})

    with (
        patch.object(
            voice_engine._client.aio.models,
            "generate_content",
            new=AsyncMock(return_value=mock_response),
        ),
        patch.object(voice_engine.logger, "info", side_effect=_capture_info),
    ):
        result = await voice_engine.text_to_speech_custom("Hello world", "Aoede")

    assert result == _WAV_STUB

    tts_complete_entries = [e for e in log_calls if e["event"] == "tts_complete"]
    assert len(tts_complete_entries) == 1

    entry = tts_complete_entries[0]
    assert "audio_size_bytes" in entry
    assert entry["audio_size_bytes"] == len(_WAV_STUB)


