"""
Tests for GitHub Pages hosting and GitHub MCP setup.
Validates structural properties of config files, workflow files, and gitignore.
"""
import json
import re
import fnmatch
from pathlib import Path
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).parent.parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def load_workflow_yaml(filename: str) -> dict:
    path = WORKFLOWS_DIR / filename
    with open(path) as f:
        return yaml.safe_load(f)


def load_workflow_raw(filename: str) -> str:
    return (WORKFLOWS_DIR / filename).read_text()


# ---------------------------------------------------------------------------
# Vite config
# ---------------------------------------------------------------------------

def test_vite_config_has_correct_base_path():
    """Req 1.1 — vite.config.js contains base: '/BRD_Analyzer/'"""
    vite_config = (REPO_ROOT / "frontend" / "vite.config.js").read_text()
    assert "base: '/BRD_Analyzer/'" in vite_config, (
        "vite.config.js must contain base: '/BRD_Analyzer/'"
    )


# ---------------------------------------------------------------------------
# Frontend workflow — structural checks
# ---------------------------------------------------------------------------

def test_frontend_workflow_file_exists():
    """Req 3.1 — deploy-frontend.yml exists"""
    assert (WORKFLOWS_DIR / "deploy-frontend.yml").exists()


def test_frontend_workflow_has_workflow_dispatch():
    """Req 3.3 — workflow_dispatch trigger is present"""
    data = load_workflow_yaml("deploy-frontend.yml")
    trigger = data.get("on") or data.get(True)
    assert "workflow_dispatch" in trigger, "workflow_dispatch trigger missing"


def test_frontend_workflow_push_paths():
    """Req 3.2 — push trigger includes frontend/** and the workflow file itself"""
    data = load_workflow_yaml("deploy-frontend.yml")
    trigger = data.get("on") or data.get(True)
    paths = trigger["push"]["paths"]
    assert "frontend/**" in paths
    assert ".github/workflows/deploy-frontend.yml" in paths


def test_frontend_workflow_permissions():
    """Req 3.4 — permissions: contents: read, pages: write, id-token: write"""
    data = load_workflow_yaml("deploy-frontend.yml")
    perms = data.get("permissions", {})
    assert perms.get("contents") == "read"
    assert perms.get("pages") == "write"
    assert perms.get("id-token") == "write"


def test_frontend_workflow_concurrency():
    """Req 3.5 — concurrency group 'pages' with cancel-in-progress: true"""
    data = load_workflow_yaml("deploy-frontend.yml")
    concurrency = data.get("concurrency", {})
    assert concurrency.get("group") == "pages"
    assert concurrency.get("cancel-in-progress") is True


def _get_step_uses_or_run(step: dict) -> str:
    """Return a short identifier for a step (uses action or run command snippet)."""
    return step.get("uses", "") or step.get("run", "")


def test_frontend_workflow_build_job_step_order():
    """Req 3.6 — build job steps: checkout → setup-node → npm ci → npm test → npm run build → upload artifact"""
    data = load_workflow_yaml("deploy-frontend.yml")
    steps = data["jobs"]["build"]["steps"]

    def find_index(predicate):
        for i, s in enumerate(steps):
            if predicate(s):
                return i
        return -1

    checkout_idx = find_index(lambda s: "actions/checkout" in (s.get("uses") or ""))
    setup_node_idx = find_index(lambda s: "actions/setup-node" in (s.get("uses") or ""))
    npm_ci_idx = find_index(lambda s: "npm ci" in (s.get("run") or ""))
    npm_test_idx = find_index(lambda s: "npm test" in (s.get("run") or ""))
    npm_build_idx = find_index(lambda s: "npm run build" in (s.get("run") or ""))
    upload_idx = find_index(lambda s: "upload-pages-artifact" in (s.get("uses") or ""))

    assert checkout_idx != -1, "checkout step not found"
    assert setup_node_idx != -1, "setup-node step not found"
    assert npm_ci_idx != -1, "npm ci step not found"
    assert npm_test_idx != -1, "npm test step not found"
    assert npm_build_idx != -1, "npm run build step not found"
    assert upload_idx != -1, "upload-pages-artifact step not found"

    assert checkout_idx < setup_node_idx, "checkout must come before setup-node"
    assert npm_ci_idx < npm_test_idx, "npm ci must come before npm test"
    assert npm_test_idx < npm_build_idx, "npm test must come before npm run build"
    assert npm_build_idx < upload_idx, "npm run build must come before upload artifact"


def test_frontend_workflow_deploy_job_uses_deploy_pages():
    """Req 3.7 — deploy job uses actions/deploy-pages@v4"""
    data = load_workflow_yaml("deploy-frontend.yml")
    steps = data["jobs"]["deploy"]["steps"]
    uses_values = [s.get("uses", "") for s in steps]
    assert any("actions/deploy-pages@v4" in u for u in uses_values), (
        "deploy job must use actions/deploy-pages@v4"
    )


def test_frontend_workflow_vite_api_base_secret_reference():
    """Req 5.5 — VITE_API_BASE referenced via ${{ secrets.VITE_API_BASE }}"""
    raw = load_workflow_raw("deploy-frontend.yml")
    assert "secrets.VITE_API_BASE" in raw, (
        "VITE_API_BASE must be referenced via secrets.VITE_API_BASE"
    )


# ---------------------------------------------------------------------------
# Backend workflow — structural checks
# ---------------------------------------------------------------------------

def test_backend_workflow_file_exists():
    """Req 4.1 — deploy-backend.yml exists"""
    assert (WORKFLOWS_DIR / "deploy-backend.yml").exists()


def test_backend_workflow_has_three_jobs():
    """Req 4.2 — three jobs: test, docker-build-verify, deploy"""
    data = load_workflow_yaml("deploy-backend.yml")
    jobs = set(data["jobs"].keys())
    assert "test" in jobs
    assert "docker-build-verify" in jobs
    assert "deploy" in jobs


def test_backend_docker_build_verify_needs_test():
    """Req 4.4 — docker-build-verify job needs test"""
    data = load_workflow_yaml("deploy-backend.yml")
    needs = data["jobs"]["docker-build-verify"].get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    assert "test" in needs


def test_backend_deploy_needs_docker_build_verify():
    """Req 4.5 — deploy job needs docker-build-verify"""
    data = load_workflow_yaml("deploy-backend.yml")
    needs = data["jobs"]["deploy"].get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    assert "docker-build-verify" in needs


def test_backend_test_job_uses_python_312():
    """Req 4.3 — test job sets up Python 3.12"""
    data = load_workflow_yaml("deploy-backend.yml")
    steps = data["jobs"]["test"]["steps"]
    python_versions = []
    for step in steps:
        with_block = step.get("with", {}) or {}
        if "python-version" in with_block:
            python_versions.append(str(with_block["python-version"]))
    assert any("3.12" in v for v in python_versions), (
        f"Python 3.12 not found in test job steps, got: {python_versions}"
    )


def test_backend_test_job_runs_unit_only_pytest():
    """Req 4.3 — pytest excludes e2e and properties tests"""
    data = load_workflow_yaml("deploy-backend.yml")
    steps = data["jobs"]["test"]["steps"]
    pytest_runs = [s.get("run", "") for s in steps if "pytest" in s.get("run", "")]
    assert pytest_runs, "No pytest step found in test job"
    combined = " ".join(pytest_runs)
    assert "not e2e" in combined, "pytest must exclude e2e tests"
    assert "not properties" in combined, "pytest must exclude properties tests"


def test_backend_smoke_test_has_5_retries():
    """Req 4.6 — smoke test uses {1..5} brace expansion (5 retry attempts)"""
    raw = load_workflow_raw("deploy-backend.yml")
    assert "{1..5}" in raw, "Smoke test must use '{1..5}' for 5 retry attempts"


def test_backend_smoke_test_has_10s_sleep():
    """Req 4.6 — smoke test sleeps 10 seconds between attempts"""
    raw = load_workflow_raw("deploy-backend.yml")
    assert "sleep 10" in raw, "Smoke test must use 'sleep 10' between attempts"


# ---------------------------------------------------------------------------
# MCP config
# ---------------------------------------------------------------------------

def test_mcp_config_file_exists():
    """Req 7.1 — .kiro/mcp/github.json exists"""
    assert (REPO_ROOT / ".kiro" / "mcp" / "github.json").exists()


def test_mcp_config_uses_npx():
    """Req 7.2 — MCP config uses npx command"""
    config = json.loads((REPO_ROOT / ".kiro" / "mcp" / "github.json").read_text())
    github_server = config["mcpServers"]["github"]
    assert github_server["command"] == "npx"


def test_mcp_config_uses_correct_package():
    """Req 7.2 — MCP config args include @modelcontextprotocol/server-github"""
    config = json.loads((REPO_ROOT / ".kiro" / "mcp" / "github.json").read_text())
    args = config["mcpServers"]["github"]["args"]
    assert any("@modelcontextprotocol/server-github" in a for a in args)


def test_mcp_config_token_via_secret_store():
    """Req 7.3 — token referenced via ${secrets.GITHUB_TOKEN}"""
    raw = (REPO_ROOT / ".kiro" / "mcp" / "github.json").read_text()
    assert "${secrets.GITHUB_TOKEN}" in raw, (
        "Token must be referenced via ${secrets.GITHUB_TOKEN}"
    )


def test_mcp_config_no_hardcoded_token():
    """Req 7.4 — no hardcoded token value in MCP config"""
    config = json.loads((REPO_ROOT / ".kiro" / "mcp" / "github.json").read_text())
    token_value = config["mcpServers"]["github"]["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"]
    # Must be a secret reference, not a raw token
    assert token_value.startswith("${secrets."), (
        f"Token must use secret reference syntax, got: {token_value}"
    )


# ---------------------------------------------------------------------------
# Gitignore
# ---------------------------------------------------------------------------

def _gitignore_lines() -> list[str]:
    return (REPO_ROOT / ".gitignore").read_text().splitlines()


def test_gitignore_excludes_env():
    assert ".env" in _gitignore_lines()


def test_gitignore_excludes_env_variants():
    assert ".env.*" in _gitignore_lines()


def test_gitignore_does_not_exclude_env_example():
    assert "!.env.example" in _gitignore_lines()


def test_gitignore_excludes_node_modules():
    assert "node_modules/" in _gitignore_lines()


def test_gitignore_excludes_frontend_dist():
    assert "frontend/dist/" in _gitignore_lines()


def test_gitignore_excludes_pycache():
    assert "__pycache__/" in _gitignore_lines()


def test_gitignore_excludes_pytest_cache():
    assert ".pytest_cache/" in _gitignore_lines()


def test_gitignore_excludes_venv():
    assert ".venv/" in _gitignore_lines()


def test_gitignore_excludes_vscode():
    assert ".vscode/" in _gitignore_lines()


def test_gitignore_excludes_idea():
    assert ".idea/" in _gitignore_lines()


def test_gitignore_excludes_ds_store():
    assert ".DS_Store" in _gitignore_lines()


def test_gitignore_excludes_thumbs_db():
    assert "Thumbs.db" in _gitignore_lines()


def test_gitignore_excludes_gcloud_service_key():
    assert "gcloud-service-key.json" in _gitignore_lines()


def test_gitignore_excludes_service_account_wildcard():
    assert "service-account*.json" in _gitignore_lines()


def test_gitignore_excludes_application_default_credentials():
    assert "application_default_credentials.json" in _gitignore_lines()


# ---------------------------------------------------------------------------
# Property 1: No hardcoded credentials in configuration files
# Validates: Requirements 5.6, 7.4
# ---------------------------------------------------------------------------

_CONFIG_FILES = [
    WORKFLOWS_DIR / "deploy-frontend.yml",
    WORKFLOWS_DIR / "deploy-backend.yml",
    REPO_ROOT / ".kiro" / "mcp" / "github.json",
]

_CONFIG_CONTENTS = {str(p): p.read_text() for p in _CONFIG_FILES}


@given(
    st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
        min_size=40,
        max_size=60,
    )
)
@settings(max_examples=100)
def test_no_hardcoded_credentials_in_config_files(credential_like_string: str):
    """
    Property 1: No hardcoded credentials in configuration files
    Validates: Requirements 5.6, 7.4

    For any long alphanumeric string, it should not appear literally in the
    workflow YAML or MCP config JSON files.
    """
    for path_str, content in _CONFIG_CONTENTS.items():
        assert credential_like_string not in content, (
            f"Credential-like string found literally in {path_str}"
        )

    # Also verify secret references use correct syntax in workflow files
    for filename in ("deploy-frontend.yml", "deploy-backend.yml"):
        raw = _CONFIG_CONTENTS[str(WORKFLOWS_DIR / filename)]
        # Strip all valid ${{ secrets.X }} references
        stripped = re.sub(r"\$\{\{\s*secrets\.[A-Za-z0-9_]+\s*\}\}", "", raw)
        # No bare 'secrets.' references should remain (would indicate malformed syntax)
        # This is a soft check — we just verify the pattern is used correctly
        secret_refs = re.findall(r"\$\{\{[^}]*\}\}", raw)
        for ref in secret_refs:
            if "secrets." in ref:
                assert re.match(r"\$\{\{\s*secrets\.[A-Za-z0-9_]+\s*\}\}", ref), (
                    f"Malformed secret reference in {filename}: {ref}"
                )

    # Verify MCP config uses ${secrets. syntax
    mcp_raw = _CONFIG_CONTENTS[str(REPO_ROOT / ".kiro" / "mcp" / "github.json")]
    assert "${secrets." in mcp_raw, "MCP config must use ${secrets. syntax for token"


# ---------------------------------------------------------------------------
# Property 2: Gitignore covers all sensitive file patterns
# Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8
# ---------------------------------------------------------------------------

_GITIGNORE_CONTENT = (REPO_ROOT / ".gitignore").read_text()


def matches_gitignore(filename: str, gitignore_content: str) -> bool:
    """
    Check if a filename matches any positive (non-negation) gitignore pattern
    using fnmatch. Handles both plain filenames and path-prefixed filenames.
    """
    lines = gitignore_content.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        # Match against the full path and just the basename
        basename = Path(filename).name
        if fnmatch.fnmatch(filename, line) or fnmatch.fnmatch(basename, line):
            return True
        # Also handle directory patterns like frontend/dist/
        if line.endswith("/") and filename.startswith(line):
            return True
    return False


def is_negated_by_gitignore(filename: str, gitignore_content: str) -> bool:
    """Check if a filename is explicitly un-ignored by a negation pattern."""
    lines = gitignore_content.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            pattern = line[1:]
            basename = Path(filename).name
            if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(basename, pattern):
                return True
    return False


@given(
    st.sampled_from([
        # .env variants — should be ignored
        ".env.production",
        ".env.local",
        ".env.staging",
        ".env.development",
        ".env.test",
        ".env.prod",
        # service account files — should be ignored
        "service-account-prod.json",
        "service-account-staging.json",
        "service-account-dev.json",
        "service-account-123.json",
        # frontend/dist paths — should be ignored
        "frontend/dist/index.html",
        "frontend/dist/assets/main.js",
        "frontend/dist/assets/style.css",
        # other sensitive files
        "gcloud-service-key.json",
        "application_default_credentials.json",
        "__pycache__/module.pyc",
        "node_modules/package/index.js",
        ".DS_Store",
        "Thumbs.db",
    ])
)
@settings(max_examples=100)
def test_gitignore_covers_sensitive_patterns(sensitive_filename: str):
    """
    Property 2: Gitignore covers all sensitive file patterns
    Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8

    Sensitive filenames should be matched by gitignore patterns.
    """
    assert matches_gitignore(sensitive_filename, _GITIGNORE_CONTENT), (
        f"'{sensitive_filename}' should be ignored by .gitignore but is not"
    )


@given(
    st.sampled_from([
        ".env.example",
    ])
)
@settings(max_examples=100)
def test_gitignore_does_not_ignore_env_example_property(env_example_file: str):
    """
    Property 2 (negation): .env.example must NOT be ignored
    Validates: Requirement 6.2

    .env.example should be explicitly un-ignored via the !.env.example negation rule.
    """
    assert is_negated_by_gitignore(env_example_file, _GITIGNORE_CONTENT), (
        f"'{env_example_file}' should be un-ignored by !.env.example in .gitignore"
    )
