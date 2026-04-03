"""
voice_engine.py — Google Gemini TTS synthesis for the Voice Assistant feature.

Mirrors the structure of gemini_engine.py: module-level genai.Client,
async functions using _client.aio.models.generate_content, structlog logging.
"""

from __future__ import annotations

import os
import time

from google import genai
from google.genai import types as _genai_types

from logging_config import get_logger

# ---------------------------------------------------------------------------
# Module-level Gemini client (initialized once at import time)
# ---------------------------------------------------------------------------
_API_KEY = os.environ.get("GOOGLE_AI_API_KEY", "")
_client = genai.Client(api_key=_API_KEY if _API_KEY else "placeholder")

_TTS_MODEL = "gemini-2.5-flash-preview-tts"
_DEFAULT_VOICE = "Aoede"
VALID_VOICES = {"Aoede", "Charon", "Fenrir", "Kore", "Puck"}

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class TTSError(Exception):
    """Raised when the TTS API call fails."""


class TTSConfigError(TTSError):
    """Raised when GOOGLE_AI_API_KEY is not configured."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_api_key() -> None:
    """Raise TTSConfigError if GOOGLE_AI_API_KEY is not set."""
    if not os.environ.get("GOOGLE_AI_API_KEY", ""):
        raise TTSConfigError("GOOGLE_AI_API_KEY not configured")


def format_story_narration(story: dict) -> str:
    """
    Format a user story dict into a narration string.

    Returns: "As a {role}, I want to {feature}, so that {benefit}. Priority: {priority}."
    """
    return (
        f"As a {story['role']}, I want to {story['feature']}, "
        f"so that {story['benefit']}. Priority: {story['priority']}."
    )


async def text_to_speech_custom(text: str, voice: str, endpoint: str = "unknown") -> bytes:
    """
    Synthesize text to WAV bytes using the specified voice.

    Raises ValueError if text is empty.
    Raises TTSError if the API call fails.
    """
    if not text:
        raise ValueError("text must be non-empty")

    logger.info("tts_start", endpoint=endpoint, voice_name=voice)
    t_start = time.monotonic()

    try:
        response = await _client.aio.models.generate_content(
            model=_TTS_MODEL,
            contents=text,
            config=_genai_types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=_genai_types.SpeechConfig(
                    voice_config=_genai_types.VoiceConfig(
                        prebuilt_voice_config=_genai_types.PrebuiltVoiceConfig(
                            voice_name=voice
                        )
                    )
                ),
            ),
        )
        audio_data: bytes = response.candidates[0].content.parts[0].inline_data.data
        duration_ms = int((time.monotonic() - t_start) * 1000)
        logger.info("tts_complete", audio_size_bytes=len(audio_data), duration_ms=duration_ms)
        return audio_data
    except (ValueError, TTSError):
        raise
    except Exception as exc:
        duration_ms = int((time.monotonic() - t_start) * 1000)
        logger.error("tts_failure", error_type=type(exc).__name__, duration_ms=duration_ms)
        raise TTSError(str(exc)) from exc


async def summarize_to_speech(analysis_result: dict) -> bytes:
    """
    Extract executive_summary from analysis_result and synthesize with Aoede.

    Thin wrapper around text_to_speech_custom.
    """
    text = analysis_result["executive_summary"]
    return await text_to_speech_custom(text, _DEFAULT_VOICE, endpoint="/voice-summary")
