"""
Unit tests for voice_engine.py core functions and voice assistant endpoints.
"""

from __future__ import annotations

import base64
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure backend/ is on the path
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import voice_engine
from requirement_summarizer_app import rs_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WAV_STUB = b"RIFF" + b"\x00" * 40  # 44-byte minimal WAV stub


def _make_tts_response(data: bytes = _WAV_STUB) -> MagicMock:
    """Build a mock TTS response with the expected nested structure."""
    part = MagicMock()
    part.inline_data.data = data

    content = MagicMock()
    content.parts = [part]

    candidate = MagicMock()
    candidate.content = content

    response = MagicMock()
    response.candidates = [candidate]
    return response


# ---------------------------------------------------------------------------
# test_format_story_narration_basic
# ---------------------------------------------------------------------------


def test_format_story_narration_basic() -> None:
    """Exact output for a known user story dict."""
    story = {
        "role": "business analyst",
        "feature": "export reports",
        "benefit": "I can share results with stakeholders",
        "priority": "high",
    }
    result = voice_engine.format_story_narration(story)
    expected = (
        "As a business analyst, I want to export reports, "
        "so that I can share results with stakeholders. Priority: high."
    )
    assert result == expected


# ---------------------------------------------------------------------------
# test_text_to_speech_custom_empty_raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_to_speech_custom_empty_raises() -> None:
    """ValueError is raised when text is an empty string."""
    with pytest.raises(ValueError, match="non-empty"):
        await voice_engine.text_to_speech_custom("", "Aoede")


# ---------------------------------------------------------------------------
# test_summarize_to_speech_delegates_to_text_to_speech_custom
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_to_speech_delegates_to_text_to_speech_custom() -> None:
    """summarize_to_speech pulls executive_summary and calls the TTS API with Aoede."""
    mock_response = _make_tts_response(_WAV_STUB)

    with patch.object(
        voice_engine._client.aio.models,
        "generate_content",
        new=AsyncMock(return_value=mock_response),
    ) as mock_generate:
        analysis_result = {"executive_summary": "This is the summary text."}
        result = await voice_engine.summarize_to_speech(analysis_result)

    assert result == _WAV_STUB
    mock_generate.assert_called_once()
    # Verify the text passed was the executive_summary
    call_kwargs = mock_generate.call_args
    assert call_kwargs.kwargs.get("contents") == "This is the summary text." or (
        len(call_kwargs.args) >= 2 and call_kwargs.args[1] == "This is the summary text."
    )


# ---------------------------------------------------------------------------
# Sync TestClient fixture (bypasses lifespan for endpoint tests)
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Sync TestClient that skips lifespan startup by patching validate_env_vars."""
    with patch("requirement_summarizer_app.validate_env_vars"), \
         patch("database.init_db", new=AsyncMock()):
        with TestClient(rs_app, raise_server_exceptions=False) as c:
            yield c


# ---------------------------------------------------------------------------
# Sub-task 2.1: /voice-summary endpoint tests
# ---------------------------------------------------------------------------


def test_voice_summary_uses_aoede(client) -> None:
    """POST /voice-summary calls summarize_to_speech (Aoede used internally)."""
    with (
        patch("voice_engine.check_api_key"),
        patch(
            "voice_engine.summarize_to_speech",
            new=AsyncMock(return_value=_WAV_STUB),
        ) as mock_summarize,
    ):
        resp = client.post(
            "/voice-summary",
            json={"executive_summary": "Hello world"},
        )
    assert resp.status_code == 200
    mock_summarize.assert_called_once()


def test_voice_summary_missing_field_returns_422(client) -> None:
    """POST /voice-summary without executive_summary returns 422."""
    resp = client.post("/voice-summary", json={"user_stories": []})
    assert resp.status_code == 422


def test_voice_summary_tts_failure_returns_502(client) -> None:
    """POST /voice-summary when TTS raises TTSError returns 502 without API key."""
    with (
        patch("voice_engine.check_api_key"),
        patch(
            "voice_engine.summarize_to_speech",
            new=AsyncMock(side_effect=voice_engine.TTSError("network error")),
        ),
    ):
        resp = client.post(
            "/voice-summary",
            json={"executive_summary": "Hello"},
        )
    assert resp.status_code == 502
    body = resp.text
    api_key = os.environ.get("GOOGLE_AI_API_KEY", "")
    if api_key:
        assert api_key not in body


def test_voice_summary_no_api_key_returns_503(client) -> None:
    """POST /voice-summary when check_api_key raises TTSConfigError returns 503."""
    with patch(
        "voice_engine.check_api_key",
        side_effect=voice_engine.TTSConfigError("GOOGLE_AI_API_KEY not configured"),
    ):
        resp = client.post(
            "/voice-summary",
            json={"executive_summary": "Hello"},
        )
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Sub-task 2.2: /voice-story endpoint tests
# ---------------------------------------------------------------------------


def test_voice_story_missing_field_returns_422(client) -> None:
    """POST /voice-story without required story field returns 422."""
    resp = client.post(
        "/voice-story",
        json={
            "story": {"role": "analyst", "feature": "export"},  # missing benefit, priority, id
            "voice": "Aoede",
        },
    )
    assert resp.status_code == 422


def test_voice_story_tts_failure_returns_502(client) -> None:
    """POST /voice-story when TTS raises TTSError returns 502."""
    with patch(
        "voice_engine.text_to_speech_custom",
        new=AsyncMock(side_effect=voice_engine.TTSError("synthesis failed")),
    ):
        resp = client.post(
            "/voice-story",
            json={
                "story": {
                    "id": "1",
                    "role": "analyst",
                    "feature": "export",
                    "benefit": "share results",
                    "priority": "high",
                },
                "voice": "Aoede",
            },
        )
    assert resp.status_code == 502


@pytest.mark.parametrize("voice", ["Aoede", "Charon", "Fenrir", "Kore", "Puck"])
def test_all_valid_voices_return_200(client, voice: str) -> None:
    """POST /voice-story with each valid voice returns 200."""
    with patch(
        "voice_engine.text_to_speech_custom",
        new=AsyncMock(return_value=_WAV_STUB),
    ):
        resp = client.post(
            "/voice-story",
            json={
                "story": {
                    "id": "1",
                    "role": "analyst",
                    "feature": "export",
                    "benefit": "share results",
                    "priority": "high",
                },
                "voice": voice,
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "audio" in data
    assert base64.b64decode(data["audio"]) == _WAV_STUB
