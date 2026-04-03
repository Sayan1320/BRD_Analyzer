"""
Standalone helpers for the Requirement Summarizer — importable without
triggering GCPMCPClient or any external service initialization.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Supported file extensions and size limit
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".tiff"}
MAX_FILE_SIZE = 20_971_520  # 20 MB

REQUIRED_ENV_VARS = [
    "GOOGLE_AI_API_KEY",
    "LLAMA_CLOUD_API_KEY",
    "ALLOYDB_INSTANCE_URI",
    "DB_USER",
    "DB_PASS",
    "DB_NAME",
]


def validate_extension(filename: str) -> bool:
    """Return True iff the lowercase extension of filename is in the supported set."""
    p = Path(filename)
    suffix = p.suffix.lower()
    # Handle dotfiles like ".tiff" where Path treats the whole name as stem
    if not suffix and p.name.startswith("."):
        suffix = p.name.lower()
    return suffix in SUPPORTED_EXTENSIONS


def validate_env_vars(env: dict | None = None) -> None:
    """
    Check that all required environment variables are present.

    Args:
        env: dict of env vars to check; defaults to os.environ.

    Raises:
        RuntimeError: identifying the missing variable name(s).
    """
    if env is None:
        env = dict(os.environ)
    missing = [var for var in REQUIRED_ENV_VARS if not env.get(var)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variable(s): {', '.join(missing)}"
        )
