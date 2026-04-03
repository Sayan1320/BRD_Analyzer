"""
Shared pytest fixtures for the Requirement Summarizer and GCP MCP client tests.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# Ensure backend/ is on the path
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


# ===========================================================================
# GCP MCP Client fixtures (pre-existing)
# ===========================================================================

class MockSubprocessController:
    """
    Controls a mock asyncio subprocess for testing GCPMCPClient.

    Usage:
        controller.set_response({"jsonrpc": "2.0", "id": 1, "result": {...}})
        message = controller.capture_sent_message()
    """

    _DEFAULT_INIT_RESPONSE = {
        "jsonrpc": "2.0",
        "id": 0,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "gcp-mcp-server", "version": "1.0.0"},
        },
    }

    def __init__(self) -> None:
        self._written: list[bytes] = []
        self._tool_response: dict | None = None
        self.process = self._build_process()

    def _build_process(self) -> MagicMock:
        written = self._written
        controller = self

        # stdin — records writes
        stdin_mock = MagicMock()
        stdin_mock.write = MagicMock(side_effect=lambda data: written.append(data))
        stdin_mock.drain = AsyncMock()
        stdin_mock.close = MagicMock()

        # stdout — returns init response first, then the configured tool response
        call_count = [0]

        async def readline() -> bytes:
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                return (json.dumps(controller._DEFAULT_INIT_RESPONSE) + "\n").encode()
            if controller._tool_response is not None:
                return (json.dumps(controller._tool_response) + "\n").encode()
            return b""

        stdout_mock = MagicMock()
        stdout_mock.readline = readline

        process_mock = MagicMock()
        process_mock.stdin = stdin_mock
        process_mock.stdout = stdout_mock
        process_mock.returncode = None
        process_mock.terminate = MagicMock()
        process_mock.kill = MagicMock()
        process_mock.wait = AsyncMock()

        return process_mock

    def set_response(self, response: dict) -> None:
        """Inject a JSON-RPC response that will be returned on the next stdout read."""
        self._tool_response = response

    def capture_sent_message(self) -> dict | None:
        """
        Return the last non-initialize JSON-RPC message written to stdin, parsed.
        Returns None if nothing has been written beyond the initialize request.
        """
        all_data = b"".join(self._written)
        messages = [
            json.loads(line)
            for line in all_data.decode().splitlines()
            if line.strip()
        ]
        non_init = [m for m in messages if not (m.get("id") == 0 and m.get("method") == "initialize")]
        return non_init[-1] if non_init else None

    def all_sent_messages(self) -> list[dict]:
        """Return all JSON-RPC messages written to stdin (including initialize)."""
        all_data = b"".join(self._written)
        return [
            json.loads(line)
            for line in all_data.decode().splitlines()
            if line.strip()
        ]


@pytest.fixture
def mock_mcp_subprocess(monkeypatch: pytest.MonkeyPatch) -> MockSubprocessController:
    """
    Patches asyncio.create_subprocess_exec to return a mock process.

    The returned controller exposes:
      - controller.set_response(dict)       — inject a JSON-RPC response on stdout
      - controller.capture_sent_message()   — inspect the last non-init stdin write
      - controller.all_sent_messages()      — all stdin writes as parsed dicts
      - controller.process                  — the raw mock process object
    """
    controller = MockSubprocessController()

    async def fake_create_subprocess(*args: Any, **kwargs: Any) -> MagicMock:
        return controller.process

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess)
    return controller


@pytest.fixture
def mock_config_path(tmp_path: Any) -> str:
    """
    Creates a temporary mcp_config.json with a valid mcpServers.gcp structure
    and returns the path to it.
    """
    config = {
        "mcpServers": {
            "gcp": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-gcp"],
                "env": {
                    "GOOGLE_CLOUD_PROJECT": "test-project",
                    "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/test-credentials.json",
                },
            }
        }
    }
    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    return str(config_file)


# ===========================================================================
# Requirement Summarizer fixtures
# ===========================================================================

# ---------------------------------------------------------------------------
# mock_gemini_client
# ---------------------------------------------------------------------------

class _MockGeminiController:
    """
    Controls the mock for google.genai client's aio.models.generate_content.

    Usage:
        mock_gemini_client.set_response('{"executive_summary": "..."}')
    """

    def __init__(self) -> None:
        self._response_text: str = "{}"

    def set_response(self, text: str) -> None:
        """Inject the raw text that the mock Gemini API will return."""
        self._response_text = text

    def _make_response(self) -> MagicMock:
        resp = MagicMock()
        resp.text = self._response_text
        return resp


@pytest.fixture
def mock_gemini_client(monkeypatch: pytest.MonkeyPatch) -> _MockGeminiController:
    """
    Patches `_client.aio.models.generate_content` in gemini_engine so no real
    Gemini API calls are made.

    The returned controller exposes:
      - controller.set_response(str)  — inject the raw text the mock will return
    """
    import gemini_engine as _gem

    controller = _MockGeminiController()

    async def _fake_generate_content(*args: Any, **kwargs: Any) -> MagicMock:
        return controller._make_response()

    monkeypatch.setattr(
        _gem._client.aio.models,
        "generate_content",
        _fake_generate_content,
    )
    return controller


# ---------------------------------------------------------------------------
# mock_llama_parse
# ---------------------------------------------------------------------------

class _MockLlamaParseController:
    """
    Controls the mock for llama_parse.LlamaParse used in ocr_engine.

    Usage:
        mock_llama_parse.set_extraction("extracted text", page_count=3)
    """

    def __init__(self) -> None:
        self._text: str = ""
        self._page_count: int = 1

    def set_extraction(self, text: str, page_count: int = 1) -> None:
        """Inject the text and page count that the mock parser will return."""
        self._text = text
        self._page_count = page_count

    def _make_nodes(self) -> list[MagicMock]:
        """Build a list of mock LlamaIndex nodes matching the configured extraction."""
        if not self._text:
            return []
        # Split text across pages evenly
        if self._page_count <= 1:
            nodes = [MagicMock()]
            nodes[0].text = self._text
            return nodes
        # Distribute text across pages
        chunk_size = max(1, len(self._text) // self._page_count)
        nodes = []
        for i in range(self._page_count):
            node = MagicMock()
            start = i * chunk_size
            end = start + chunk_size if i < self._page_count - 1 else len(self._text)
            node.text = self._text[start:end]
            nodes.append(node)
        return nodes


@pytest.fixture
def mock_llama_parse(monkeypatch: pytest.MonkeyPatch) -> _MockLlamaParseController:
    """
    Patches `ocr_engine._llama_parser` so no real LlamaParse API calls are made.

    The returned controller exposes:
      - controller.set_extraction(text, page_count)  — inject extraction result
    """
    import ocr_engine as _ocr

    controller = _MockLlamaParseController()

    mock_parser = MagicMock()

    def _fake_load_data(path: str) -> list[MagicMock]:
        return controller._make_nodes()

    mock_parser.load_data = _fake_load_data

    monkeypatch.setattr(_ocr, "_llama_parser", mock_parser)
    return controller


# ---------------------------------------------------------------------------
# mock_db_session
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def mock_db_session():
    """
    Provides an in-memory async SQLite session pre-configured with the ORM models.

    Uses sqlite+aiosqlite:///:memory: with StaticPool so the same in-memory DB
    is shared across all connections within the test.

    Yields an AsyncSession that tests can use directly or pass to database.py helpers.
    """
    from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from datetime import datetime, timezone
    import uuid as _uuid

    class _Base(DeclarativeBase):
        pass

    def _now() -> datetime:
        return datetime.now(timezone.utc)

    class _Session(_Base):
        __tablename__ = "sessions"
        id: Mapped[str] = mapped_column(
            String(36), primary_key=True, default=lambda: str(_uuid.uuid4())
        )
        filename: Mapped[str] = mapped_column(String(255), nullable=False)
        file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
        status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")
        page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
        char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
        result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), nullable=False, default=_now
        )
        updated_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), nullable=False, default=_now
        )
        audit_logs: Mapped[list["_AuditLog"]] = relationship(
            "_AuditLog", back_populates="session", cascade="all, delete-orphan"
        )

    class _AuditLog(_Base):
        __tablename__ = "audit_logs"
        id: Mapped[str] = mapped_column(
            String(36), primary_key=True, default=lambda: str(_uuid.uuid4())
        )
        session_id: Mapped[str] = mapped_column(
            String(36), ForeignKey("sessions.id"), nullable=False
        )
        event_type: Mapped[str] = mapped_column(String(50), nullable=False)
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), nullable=False, default=_now
        )
        session: Mapped[_Session] = relationship("_Session", back_populates="audit_logs")

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        yield session

    await engine.dispose()


# ---------------------------------------------------------------------------
# test_client
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def test_client(mock_gemini_client: _MockGeminiController, mock_llama_parse: _MockLlamaParseController):
    """
    Creates an httpx.AsyncClient wrapping the rs_app FastAPI app with all
    external dependencies mocked (DB, OCR, Gemini).

    Depends on mock_gemini_client and mock_llama_parse so those patches are
    already active when the client is created.
    """
    from unittest.mock import patch, AsyncMock
    from httpx import AsyncClient, ASGITransport
    from ocr_engine import ExtractionResult
    from gemini_engine import AnalysisResult, UserStory
    import requirement_summarizer_app as _rs_module

    _mock_session_record = MagicMock()
    _mock_session_record.id = "00000000-0000-0000-0000-000000000001"
    _mock_db = AsyncMock()

    async def _fake_get_session():
        yield _mock_db

    _mock_extraction = ExtractionResult(text="test content", char_count=12, page_count=1)
    _mock_analysis = AnalysisResult(
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
        patch("ocr_engine.extract_text", return_value=_mock_extraction),
    ):
        transport = ASGITransport(app=_rs_module.rs_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


# ---------------------------------------------------------------------------
# reset_rate_limiter — autouse fixture to clear limiter state between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Disable the rate limiter during tests to prevent rate limit state from
    interfering with test assertions."""
    from rate_limiter import limiter
    original_enabled = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original_enabled
    limiter._storage.reset()
