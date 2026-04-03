"""
Property-based tests for the Voice Assistant feature.
Uses hypothesis with @settings(max_examples=100).
"""

from __future__ import annotations

import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis.strategies import text, sampled_from

# Ensure backend/ is on the path
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import voice_engine
from voice_engine import VALID_VOICES, format_story_narration, text_to_speech_custom

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
# Feature: voice-assistant, Property 1: Story narration text contains all user story fields
# ---------------------------------------------------------------------------


# Feature: voice-assistant, Property 1: Story narration text contains all user story fields
@given(
    role=text(min_size=1),
    feature=text(min_size=1),
    benefit=text(min_size=1),
    priority=text(min_size=1),
)
@settings(max_examples=100)
def test_story_narration_contains_all_fields(
    role: str, feature: str, benefit: str, priority: str
) -> None:
    """
    Validates: Requirements 2.2, 5.4

    For any non-empty role, feature, benefit, and priority, format_story_narration
    must contain each field value as a substring and match the expected template.
    """
    story = {"role": role, "feature": feature, "benefit": benefit, "priority": priority}
    result = format_story_narration(story)

    assert role in result, f"role {role!r} not found in {result!r}"
    assert feature in result, f"feature {feature!r} not found in {result!r}"
    assert benefit in result, f"benefit {benefit!r} not found in {result!r}"
    assert priority in result, f"priority {priority!r} not found in {result!r}"

    expected = (
        f"As a {role}, I want to {feature}, so that {benefit}. Priority: {priority}."
    )
    assert result == expected, f"Template mismatch.\nExpected: {expected!r}\nGot: {result!r}"


# ---------------------------------------------------------------------------
# Feature: voice-assistant, Property 6: text_to_speech_custom returns non-empty bytes
# ---------------------------------------------------------------------------


# Feature: voice-assistant, Property 6: text_to_speech_custom returns non-empty bytes for any valid input
@given(
    text_input=text(min_size=1),
    voice=sampled_from(list(VALID_VOICES)),
)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_tts_returns_non_empty_bytes(text_input: str, voice: str) -> None:
    """
    Validates: Requirements 5.3

    For any non-empty text and valid voice, text_to_speech_custom must return
    a non-empty bytes object.
    """
    mock_response = _make_tts_response(_WAV_STUB)

    with patch.object(
        voice_engine._client.aio.models,
        "generate_content",
        new=AsyncMock(return_value=mock_response),
    ):
        result = await text_to_speech_custom(text_input, voice)

    assert isinstance(result, bytes), f"Expected bytes, got {type(result)}"
    assert len(result) > 0, "Expected non-empty bytes"


# ---------------------------------------------------------------------------
# Feature: voice-assistant, Property 3: WAV bytes begin with RIFF header
# ---------------------------------------------------------------------------


# Feature: voice-assistant, Property 3: WAV bytes begin with RIFF header
@given(
    text_input=text(min_size=1),
    voice=sampled_from(list(VALID_VOICES)),
)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_tts_returns_riff_header(text_input: str, voice: str) -> None:
    """
    Validates: Requirements 3.6

    For any non-empty text and valid voice, the bytes returned by
    text_to_speech_custom must begin with b"RIFF".
    """
    mock_response = _make_tts_response(_WAV_STUB)

    with patch.object(
        voice_engine._client.aio.models,
        "generate_content",
        new=AsyncMock(return_value=mock_response),
    ):
        result = await text_to_speech_custom(text_input, voice)

    assert result[:4] == b"RIFF", f"Expected RIFF header, got {result[:4]!r}"


# ---------------------------------------------------------------------------
# Feature: voice-assistant, Property 7: Voice engine uses the correct TTS model name
# ---------------------------------------------------------------------------


# Feature: voice-assistant, Property 7: Voice engine uses the correct TTS model name
@given(
    text_input=text(min_size=1),
    voice=sampled_from(list(VALID_VOICES)),
)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_tts_uses_correct_model(text_input: str, voice: str) -> None:
    """
    Validates: Requirements 3.3

    For any non-empty text and valid voice, the model argument passed to
    _client.aio.models.generate_content must equal "gemini-2.5-flash-preview-tts".
    """
    mock_response = _make_tts_response(_WAV_STUB)
    captured_model: list[str] = []

    async def _capture_generate_content(*args, **kwargs):
        # model is passed as keyword arg
        captured_model.append(kwargs.get("model", args[0] if args else ""))
        return mock_response

    with patch.object(
        voice_engine._client.aio.models,
        "generate_content",
        new=_capture_generate_content,
    ):
        await text_to_speech_custom(text_input, voice)

    assert len(captured_model) == 1
    assert captured_model[0] == "gemini-2.5-flash-preview-tts", (
        f"Expected model 'gemini-2.5-flash-preview-tts', got {captured_model[0]!r}"
    )


# ---------------------------------------------------------------------------
# Endpoint tests (Properties 2 and 5) — require TestClient
# ---------------------------------------------------------------------------

import base64 as _base64
from fastapi.testclient import TestClient
from hypothesis.strategies import binary
from requirement_summarizer_app import rs_app


# Feature: voice-assistant, Property 2: Endpoint returns valid base64 WAV in AudioResponse
@given(wav_bytes=binary(min_size=44))
@settings(max_examples=100)
def test_voice_summary_returns_valid_base64_audio(wav_bytes: bytes) -> None:
    """
    Validates: Requirements 1.2, 2.6, 5.2

    For any WAV bytes (min 44 bytes), POST /voice-summary returns 200 and
    the audio field decodes back to the original bytes.
    """
    with (
        patch("requirement_summarizer_app.validate_env_vars"),
        patch("database.init_db", new=AsyncMock()),
        patch("voice_engine.check_api_key"),
        patch(
            "voice_engine.summarize_to_speech",
            new=AsyncMock(return_value=wav_bytes),
        ),
    ):
        with TestClient(rs_app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/voice-summary",
                json={"executive_summary": "test summary"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "audio" in data
    # Must be valid base64
    decoded = _base64.b64decode(data["audio"])
    assert decoded == wav_bytes


# Feature: voice-assistant, Property 5: Invalid voice name returns HTTP 422
@given(voice=text().filter(lambda v: v not in {"Aoede", "Charon", "Fenrir", "Kore", "Puck"}))
@settings(max_examples=100)
def test_invalid_voice_returns_422(voice: str) -> None:
    """
    Validates: Requirements 2.4

    For any string not in the valid voice set, POST /voice-story returns 422.
    """
    with (
        patch("requirement_summarizer_app.validate_env_vars"),
        patch("database.init_db", new=AsyncMock()),
    ):
        with TestClient(rs_app, raise_server_exceptions=False) as client:
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
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Feature: voice-assistant, Property 4: Base64 encoding is a lossless round-trip
# ---------------------------------------------------------------------------


# Feature: voice-assistant, Property 4: Base64 encoding is a lossless round-trip
@given(data=binary())
@settings(max_examples=100)
def test_base64_round_trip(data: bytes) -> None:
    """
    Validates: Requirements 5.1

    For any sequence of bytes, encoding with base64.b64encode and then decoding
    with base64.b64decode must return bytes identical to the original.
    """
    import base64
    encoded = base64.b64encode(data)
    decoded = base64.b64decode(encoded)
    assert decoded == data
