"""
ocr_engine.py — LlamaParse text extraction for the Requirement Summarizer.

For .txt files: decodes bytes as UTF-8 directly (no API key required).
For all other supported types: writes bytes to a temp file, calls LlamaParse,
concatenates node text, and counts pages from nodes.

Returns ExtractionResult("", 0, 0) for empty or unreadable files instead of raising.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception
from logging_config import get_logger

# ---------------------------------------------------------------------------
# LlamaParse — optional import (requires LLAMA_CLOUD_API_KEY at runtime)
# ---------------------------------------------------------------------------
try:
    from llama_parse import LlamaParse as _LlamaParse  # type: ignore
    _LLAMA_PARSE_AVAILABLE = True
except ImportError:
    _LlamaParse = None  # type: ignore
    _LLAMA_PARSE_AVAILABLE = False

# ---------------------------------------------------------------------------
# Module-level LlamaParse instance (created once if API key is present)
# ---------------------------------------------------------------------------
_llama_parser = None
if _LLAMA_PARSE_AVAILABLE and os.environ.get("LLAMA_CLOUD_API_KEY"):
    _llama_parser = _LlamaParse(
        api_key=os.environ["LLAMA_CLOUD_API_KEY"],
        result_type="text",
    )

# ---------------------------------------------------------------------------
# Supported file extensions
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".tiff"}


# ---------------------------------------------------------------------------
# Tenacity retry helpers for LlamaParse (Req 9.5)
# ---------------------------------------------------------------------------
def _log_ocr_retry(retry_state):
    log = get_logger("ocr_engine")
    filename = retry_state.kwargs.get("filename", "unknown") if retry_state.kwargs else "unknown"
    log.warning(
        "llamaparse_retry",
        attempt_number=retry_state.attempt_number,
        filename=filename,
    )


@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(3),
    retry=retry_if_exception(lambda exc: not isinstance(exc, ValueError)),
    reraise=True,
    before_sleep=_log_ocr_retry,
)
def _load_data(tmp_path: str, filename: str = "unknown") -> list:
    return _llama_parser.load_data(tmp_path)


@dataclass
class ExtractionResult:
    text: str
    char_count: int
    page_count: int


def extract_text(file_bytes: bytes, filename: str) -> ExtractionResult:
    """
    Extract text from file bytes.

    - .txt files: decoded directly as UTF-8, no API call needed.
    - Other supported types: written to a temp file and parsed via LlamaParse.
    - Returns ExtractionResult("", 0, 0) for empty or unreadable files.
    """
    if not file_bytes:
        return ExtractionResult("", 0, 0)

    ext = Path(filename).suffix.lower()

    # --- Plain text fast path (no API key required) ---
    if ext == ".txt":
        try:
            text = file_bytes.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            return ExtractionResult("", 0, 0)

        if not text:
            return ExtractionResult("", 0, 0)

        char_count = len(text)
        page_count = 1 if text else 0
        return ExtractionResult(text=text, char_count=char_count, page_count=page_count)

    # --- LlamaParse path for all other supported types ---
    if ext not in SUPPORTED_EXTENSIONS:
        return ExtractionResult("", 0, 0)

    if _llama_parser is None:
        # LlamaParse not available or API key not set
        return ExtractionResult("", 0, 0)

    try:
        suffix = ext if ext else ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            nodes = _load_data(tmp_path, filename=filename)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if not nodes:
            return ExtractionResult("", 0, 0)

        text = "\n".join(node.text for node in nodes if node.text)
        char_count = len(text)
        page_count = len(nodes)

        if not text:
            return ExtractionResult("", 0, 0)

        return ExtractionResult(text=text, char_count=char_count, page_count=page_count)

    except Exception:
        return ExtractionResult("", 0, 0)
