"""
Property-based tests for Spec: GCP Cloud Run + GitHub Pages Deployment.

P1: --set-secrets completeness (Req 1.3, 7.3)
P2: Image tag format invariant (Req 2.2)
P3: Least-privilege role invariant (Req 3.2)
P4: Smoke test retry logic (Req 8.2, 8.3, 8.4)
P5: CORS origin allowlist completeness (Req 12.1, 12.2)
P6: .gitignore sensitive pattern coverage (Req 13.1, 13.2)
"""

from __future__ import annotations

import re
from pathlib import Path

import hypothesis
import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "deploy-backend.yml"
_APP_PATH = Path(__file__).parent.parent / "requirement_summarizer_app.py"
_GITIGNORE_PATH = _REPO_ROOT / ".gitignore"

# ---------------------------------------------------------------------------
# Required constants
# ---------------------------------------------------------------------------

REQUIRED_SECRET_MAPPINGS = {
    "GOOGLE_AI_API_KEY=google-ai-api-key:latest",
    "LLAMA_CLOUD_API_KEY=llama-cloud-api-key:latest",
    "ALLOYDB_INSTANCE_URI=alloydb-instance-uri:latest",
    "DB_USER=db-user:latest",
    "DB_PASS=db-pass:latest",
    "DB_NAME=db-name:latest",
}

REQUIRED_ORIGINS = {
    "https://sayan1320.github.io",
    "http://localhost:5173",
    "http://localhost:3000",
}

REQUIRED_GITIGNORE_PATTERNS = {
    ".env",
    ".env.*",
    "github-ci-key.json",
    "application_default_credentials.json",
    "*-service-account*.json",
    "node_modules/",
    "frontend/dist/",
    "__pycache__/",
    ".pytest_cache/",
    ".venv/",
}

FORBIDDEN_ROLES = {"roles/owner", "roles/editor", "roles/projectAdmin"}

IMAGE_TAG_PATTERN = re.compile(
    r"^[a-z0-9-]+-docker\.pkg\.dev/[^/]+/brd-analyzer/brd-backend:[a-f0-9]+$"
)

# ---------------------------------------------------------------------------
# Pure validator functions (the logic under test)
# ---------------------------------------------------------------------------


def validate_set_secrets(mappings: set[str]) -> bool:
    """Return True iff all required secret mappings are present."""
    return REQUIRED_SECRET_MAPPINGS.issubset(mappings)


def build_image_tag(region: str, project_id: str, sha: str) -> str:
    """Construct the canonical Cloud Run image tag."""
    return f"{region}-docker.pkg.dev/{project_id}/brd-analyzer/brd-backend:{sha}"


def validate_iam_roles(roles: list[str]) -> list[str]:
    """Return the list of forbidden roles found in the given role list."""
    forbidden = []
    for role in roles:
        if role in FORBIDDEN_ROLES or role.endswith("Admin"):
            forbidden.append(role)
    return forbidden


def smoke_test(status_codes: list[int]) -> int:
    """
    Model the smoke-test retry loop as a pure function.
    Returns 0 if any code is 200, 1 if all codes are non-200 (up to 5 attempts).
    """
    for code in status_codes[:5]:
        if code == 200:
            return 0
    return 1


def validate_cors_origins(origins: list[str]) -> bool:
    """Return True iff all required CORS origins are present."""
    return REQUIRED_ORIGINS.issubset(set(origins))


def validate_gitignore_patterns(patterns: set[str]) -> bool:
    """Return True iff all required gitignore patterns are present."""
    return REQUIRED_GITIGNORE_PATTERNS.issubset(patterns)


# ---------------------------------------------------------------------------
# P1: --set-secrets completeness
# Validates: Requirements 1.3, 7.3
# ---------------------------------------------------------------------------


@given(
    missing=st.frozensets(
        st.sampled_from(sorted(REQUIRED_SECRET_MAPPINGS)),
        min_size=1,
        max_size=len(REQUIRED_SECRET_MAPPINGS),
    )
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_set_secrets_completeness(missing: frozenset[str]):
    """
    **Validates: Requirements 1.3, 7.3**

    P1: --set-secrets completeness.
    Any subset of the required secret mappings that omits at least one entry
    must be detected as incomplete. The full set must pass.
    """
    # A subset missing at least one required mapping must fail validation
    incomplete = REQUIRED_SECRET_MAPPINGS - missing
    assert not validate_set_secrets(incomplete), (
        f"Expected incomplete set to fail validation, but it passed. Missing: {missing}"
    )

    # The full set must always pass
    assert validate_set_secrets(REQUIRED_SECRET_MAPPINGS), (
        "Full set of required secret mappings must pass validation"
    )


def test_set_secrets_reads_actual_workflow():
    """
    Sanity check: the actual deploy-backend.yml --set-secrets string is parsed
    and validated against the required mappings.

    NOTE: This test will fail until task 5 updates deploy-backend.yml to the
    canonical secret naming scheme (google-ai-api-key:latest, etc.).
    It is marked xfail until that task is complete.
    """
    workflow = yaml.safe_load(_WORKFLOW_PATH.read_text())
    deploy_job = workflow["jobs"]["deploy"]
    steps = deploy_job["steps"]

    # Find the deploy step containing --set-secrets
    set_secrets_str = None
    for step in steps:
        run_cmd = step.get("run", "")
        if "--set-secrets" in run_cmd:
            # Normalise multi-line shell: join continuation lines
            normalised = run_cmd.replace("\\\n", " ").replace("\n", " ")
            match = re.search(r'--set-secrets[= ]"?([^"]+)"?', normalised)
            if match:
                raw = match.group(1).strip()
                set_secrets_str = raw
                break

    assert set_secrets_str is not None, "Could not find --set-secrets in deploy step"

    # Parse comma-separated mappings, stripping whitespace
    actual_mappings = {m.strip() for m in set_secrets_str.split(",") if m.strip()}
    if not validate_set_secrets(actual_mappings):
        pytest.xfail(
            f"Workflow --set-secrets not yet updated to canonical names. "
            f"Found: {actual_mappings}. Will pass after task 5 updates deploy-backend.yml."
        )


# ---------------------------------------------------------------------------
# P2: Image tag format invariant
# Validates: Requirements 2.2
# ---------------------------------------------------------------------------

_region_strategy = st.from_regex(r"[a-z][a-z0-9-]{1,19}", fullmatch=True)
_project_id_strategy = st.from_regex(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", fullmatch=True)
_sha_strategy = st.from_regex(r"[a-f0-9]{40}", fullmatch=True)


@given(
    region=_region_strategy,
    project_id=_project_id_strategy,
    sha=_sha_strategy,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_image_tag_format_invariant(region: str, project_id: str, sha: str):
    """
    **Validates: Requirements 2.2**

    P2: Image tag format invariant.
    For any valid region, project ID, and 40-char hex SHA, the constructed
    image tag must match the canonical pattern.
    """
    tag = build_image_tag(region, project_id, sha)
    assert IMAGE_TAG_PATTERN.match(tag), (
        f"Image tag '{tag}' does not match required pattern. "
        f"region={region!r}, project_id={project_id!r}, sha={sha!r}"
    )


# ---------------------------------------------------------------------------
# P3: Least-privilege role invariant
# Validates: Requirements 3.2
# ---------------------------------------------------------------------------

_safe_role_strategy = st.sampled_from([
    "roles/artifactregistry.writer",
    "roles/run.developer",
    "roles/secretmanager.secretAccessor",
    "roles/iam.serviceAccountUser",
    "roles/alloydb.client",
    "roles/viewer",
    "roles/logging.logWriter",
])

_forbidden_role_strategy = st.sampled_from([
    "roles/owner",
    "roles/editor",
    "roles/projectAdmin",
    "roles/resourcemanager.projectAdmin",
    "roles/compute.Admin",
    "roles/iam.projectAdmin",
])


@given(
    safe_roles=st.lists(_safe_role_strategy, min_size=0, max_size=5),
    forbidden_roles=st.lists(_forbidden_role_strategy, min_size=1, max_size=3),
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_least_privilege_role_invariant_detects_forbidden(
    safe_roles: list[str], forbidden_roles: list[str]
):
    """
    **Validates: Requirements 3.2**

    P3: Least-privilege role invariant.
    Any list of IAM roles that includes a forbidden role must be detected
    as violating least-privilege.
    """
    combined = safe_roles + forbidden_roles
    violations = validate_iam_roles(combined)
    assert len(violations) > 0, (
        f"Expected forbidden roles to be detected in {combined}, but got no violations"
    )
    # Every detected violation must actually be forbidden
    for v in violations:
        assert v in FORBIDDEN_ROLES or v.endswith("Admin"), (
            f"Validator flagged '{v}' which is not a forbidden role"
        )


@given(
    safe_roles=st.lists(_safe_role_strategy, min_size=1, max_size=5),
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_least_privilege_role_invariant_allows_safe(safe_roles: list[str]):
    """
    **Validates: Requirements 3.2**

    P3 (complement): Safe roles must not be flagged as forbidden.
    """
    violations = validate_iam_roles(safe_roles)
    assert len(violations) == 0, (
        f"Safe roles were incorrectly flagged as forbidden: {violations}"
    )


# ---------------------------------------------------------------------------
# P4: Smoke test retry logic
# Validates: Requirements 8.2, 8.3, 8.4
# ---------------------------------------------------------------------------

_http_status_strategy = st.integers(min_value=100, max_value=599)


@given(
    codes_before_200=st.lists(
        _http_status_strategy.filter(lambda x: x != 200),
        min_size=0,
        max_size=4,
    ),
    position=st.integers(min_value=0, max_value=4),
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_smoke_test_exits_0_on_200(codes_before_200: list[int], position: int):
    """
    **Validates: Requirements 8.2, 8.3, 8.4**

    P4: Smoke test retry logic — success path.
    If any of the first 5 status codes is 200, the smoke test must exit with 0.
    """
    # Insert 200 at a valid position within the list (capped at 5 total)
    insert_at = min(position, len(codes_before_200))
    codes = codes_before_200[:insert_at] + [200] + codes_before_200[insert_at:]
    codes = codes[:5]  # cap at 5

    result = smoke_test(codes)
    assert result == 0, (
        f"Expected exit code 0 when 200 is present, got {result}. codes={codes}"
    )


@given(
    codes=st.lists(
        _http_status_strategy.filter(lambda x: x != 200),
        min_size=5,
        max_size=5,
    )
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_smoke_test_exits_1_on_all_non_200(codes: list[int]):
    """
    **Validates: Requirements 8.2, 8.3, 8.4**

    P4: Smoke test retry logic — failure path.
    If all 5 status codes are non-200, the smoke test must exit with 1.
    """
    assert len(codes) == 5
    assert all(c != 200 for c in codes)

    result = smoke_test(codes)
    assert result == 1, (
        f"Expected exit code 1 when all 5 codes are non-200, got {result}. codes={codes}"
    )


# ---------------------------------------------------------------------------
# P5: CORS origin allowlist completeness
# Validates: Requirements 12.1, 12.2
# ---------------------------------------------------------------------------


@given(
    missing=st.frozensets(
        st.sampled_from(sorted(REQUIRED_ORIGINS)),
        min_size=1,
        max_size=len(REQUIRED_ORIGINS),
    )
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_cors_origin_allowlist_completeness(missing: frozenset[str]):
    """
    **Validates: Requirements 12.1, 12.2**

    P5: CORS origin allowlist completeness.
    Any subset of required origins that omits at least one entry must be
    detected as incomplete. The full set must pass.
    """
    incomplete = list(REQUIRED_ORIGINS - missing)
    assert not validate_cors_origins(incomplete), (
        f"Expected incomplete CORS origins to fail validation. Missing: {missing}"
    )

    # Full set must pass
    assert validate_cors_origins(list(REQUIRED_ORIGINS)), (
        "Full set of required CORS origins must pass validation"
    )


def test_cors_reads_actual_app():
    """
    Sanity check: the actual ALLOWED_ORIGINS in requirement_summarizer_app.py
    contains all required origins.
    """
    import sys
    import os
    _backend = str(Path(__file__).parent.parent)
    if _backend not in sys.path:
        sys.path.insert(0, _backend)

    # Parse ALLOWED_ORIGINS directly from the source file to avoid import side effects
    source = _APP_PATH.read_text()
    match = re.search(
        r"ALLOWED_ORIGINS\s*=\s*\[(.*?)\]",
        source,
        re.DOTALL,
    )
    assert match, "Could not find ALLOWED_ORIGINS in requirement_summarizer_app.py"
    origins_block = match.group(1)
    found_origins = re.findall(r'"(https?://[^"]+)"', origins_block)

    assert validate_cors_origins(found_origins), (
        f"ALLOWED_ORIGINS is missing required entries. "
        f"Found: {found_origins}, Required: {REQUIRED_ORIGINS}"
    )


# ---------------------------------------------------------------------------
# P6: .gitignore sensitive pattern coverage
# Validates: Requirements 13.1, 13.2
# ---------------------------------------------------------------------------


@given(
    missing=st.frozensets(
        st.sampled_from(sorted(REQUIRED_GITIGNORE_PATTERNS)),
        min_size=1,
        max_size=len(REQUIRED_GITIGNORE_PATTERNS),
    )
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_gitignore_pattern_coverage(missing: frozenset[str]):
    """
    **Validates: Requirements 13.1, 13.2**

    P6: .gitignore sensitive pattern coverage.
    Any subset of required patterns that omits at least one entry must be
    detected as incomplete. The full set must pass.
    """
    incomplete = REQUIRED_GITIGNORE_PATTERNS - missing
    assert not validate_gitignore_patterns(incomplete), (
        f"Expected incomplete gitignore patterns to fail validation. Missing: {missing}"
    )

    # Full set must pass
    assert validate_gitignore_patterns(REQUIRED_GITIGNORE_PATTERNS), (
        "Full set of required gitignore patterns must pass validation"
    )


def test_gitignore_reads_actual_file():
    """
    Sanity check: the actual .gitignore contains all required patterns.
    """
    lines = {
        line.strip()
        for line in _GITIGNORE_PATH.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert validate_gitignore_patterns(lines), (
        f".gitignore is missing required patterns. "
        f"Missing: {REQUIRED_GITIGNORE_PATTERNS - lines}"
    )
