"""Tests for Dockerfile and .dockerignore structure (Requirement 8)."""
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / "backend" / ".dockerignore"


def test_dockerfile_uses_python_312():
    """6.1 - Dockerfile must use python:3.12 base image."""
    content = DOCKERFILE.read_text()
    assert "python:3.12" in content


def test_dockerfile_has_non_root_user():
    """6.2 - Dockerfile must switch to non-root user appuser."""
    content = DOCKERFILE.read_text()
    assert "USER appuser" in content


def test_dockerfile_exposes_port_8080():
    """6.3 - Dockerfile must expose port 8080."""
    content = DOCKERFILE.read_text()
    assert "8080" in content


def test_dockerfile_has_healthcheck():
    """6.4 - Dockerfile must include a HEALTHCHECK instruction."""
    content = DOCKERFILE.read_text()
    assert "HEALTHCHECK" in content


def test_dockerignore_excludes_env_file():
    """6.5 - .dockerignore must exclude .env files."""
    content = DOCKERIGNORE.read_text()
    assert ".env" in content


def test_dockerignore_excludes_tests_directory():
    """6.6 - .dockerignore must exclude the tests/ directory."""
    content = DOCKERIGNORE.read_text()
    assert "tests/" in content
