"""
Tests for GCP Cloud Run + GitHub Pages deployment configuration.
Validates structural properties of workflow files, CORS config, Vite config, and gitignore.

Tests that depend on the updated deploy-backend.yml (task 5) are marked xfail(strict=False).
Tests that depend on deploy-frontend.yml (task 6) are marked xfail(strict=False).
"""
import pytest
import yaml
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def load_workflow_yaml(filename: str) -> dict:
    path = WORKFLOWS_DIR / filename
    with open(path) as f:
        return yaml.safe_load(f)


def load_workflow_raw(filename: str) -> str:
    return (WORKFLOWS_DIR / filename).read_text()


# ---------------------------------------------------------------------------
# Backend workflow — trigger
# ---------------------------------------------------------------------------

def test_backend_workflow_trigger_paths_includes_backend():
    """Req 5.1 — push trigger paths includes backend/**"""
    data = load_workflow_yaml("deploy-backend.yml")
    trigger = data.get("on") or data.get(True)
    paths = trigger["push"]["paths"]
    assert "backend/**" in paths


# ---------------------------------------------------------------------------
# Backend workflow — job dependency chain (requires task 5 updates)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_job_dependency_docker_build_verify_needs_test():
    """Req 5.3 — docker-build-verify job needs test"""
    data = load_workflow_yaml("deploy-backend.yml")
    needs = data["jobs"]["docker-build-verify"].get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    assert "test" in needs


@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_job_dependency_deploy_needs_docker_build_verify():
    """Req 5.3 — deploy job needs docker-build-verify"""
    data = load_workflow_yaml("deploy-backend.yml")
    needs = data["jobs"]["deploy"].get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    assert "docker-build-verify" in needs


# ---------------------------------------------------------------------------
# Backend workflow — test job (requires task 5 updates)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_test_job_python_version_312():
    """Req 5.4 — test job uses python-version: '3.12'"""
    data = load_workflow_yaml("deploy-backend.yml")
    steps = data["jobs"]["test"]["steps"]
    python_versions = [
        str(s.get("with", {}).get("python-version", ""))
        for s in steps
        if "python-version" in (s.get("with") or {})
    ]
    assert any("3.12" in v for v in python_versions), (
        f"Python 3.12 not found in test job steps, got: {python_versions}"
    )


@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_test_job_installs_from_backend_requirements():
    """Req 5.4 — test job installs from backend/requirements.txt"""
    data = load_workflow_yaml("deploy-backend.yml")
    steps = data["jobs"]["test"]["steps"]
    run_commands = [s.get("run", "") for s in steps]
    assert any("backend/requirements.txt" in cmd for cmd in run_commands), (
        "test job must install from backend/requirements.txt"
    )


@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_test_job_pytest_uses_tb_short():
    """Req 5.2 — pytest command uses --tb=short"""
    data = load_workflow_yaml("deploy-backend.yml")
    steps = data["jobs"]["test"]["steps"]
    pytest_runs = [s.get("run", "") for s in steps if "pytest" in s.get("run", "")]
    assert pytest_runs, "No pytest step found in test job"
    combined = " ".join(pytest_runs)
    assert "--tb=short" in combined, "pytest must use --tb=short"


@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_test_job_pytest_excludes_e2e_and_properties():
    """Req 5.2 — pytest -k filter excludes e2e and properties"""
    data = load_workflow_yaml("deploy-backend.yml")
    steps = data["jobs"]["test"]["steps"]
    pytest_runs = [s.get("run", "") for s in steps if "pytest" in s.get("run", "")]
    assert pytest_runs, "No pytest step found in test job"
    combined = " ".join(pytest_runs)
    assert "not e2e" in combined, "pytest must exclude e2e tests"
    assert "not properties" in combined, "pytest must exclude properties tests"


# ---------------------------------------------------------------------------
# Backend workflow — deploy job auth (requires task 5 updates)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_deploy_uses_gcp_auth_v2():
    """Req 7.1 — deploy job uses google-github-actions/auth@v2"""
    data = load_workflow_yaml("deploy-backend.yml")
    steps = data["jobs"]["deploy"]["steps"]
    uses_values = [s.get("uses", "") for s in steps]
    assert any("google-github-actions/auth@v2" in u for u in uses_values), (
        "deploy job must use google-github-actions/auth@v2"
    )


@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_deploy_auth_uses_credentials_json_secret():
    """Req 7.1 — auth step uses credentials_json: ${{ secrets.GCP_SA_KEY }}"""
    data = load_workflow_yaml("deploy-backend.yml")
    steps = data["jobs"]["deploy"]["steps"]
    for step in steps:
        if "google-github-actions/auth" in (step.get("uses") or ""):
            with_block = step.get("with") or {}
            assert "credentials_json" in with_block, "auth step must have credentials_json"
            assert "GCP_SA_KEY" in str(with_block["credentials_json"]), (
                "credentials_json must reference secrets.GCP_SA_KEY"
            )
            return
    pytest.fail("google-github-actions/auth step not found in deploy job")


# ---------------------------------------------------------------------------
# Backend workflow — gcloud deploy flags (requires task 5 updates)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_deploy_gcloud_flag_platform_managed():
    """Req 7.2 — gcloud run deploy uses --platform=managed"""
    raw = load_workflow_raw("deploy-backend.yml")
    assert "--platform=managed" in raw, "gcloud run deploy must include --platform=managed"


@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_deploy_gcloud_flag_allow_unauthenticated():
    """Req 7.2 — gcloud run deploy uses --allow-unauthenticated"""
    raw = load_workflow_raw("deploy-backend.yml")
    assert "--allow-unauthenticated" in raw, (
        "gcloud run deploy must include --allow-unauthenticated"
    )


@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_deploy_gcloud_flag_port_8080():
    """Req 7.2 — gcloud run deploy uses --port=8080"""
    raw = load_workflow_raw("deploy-backend.yml")
    assert "--port=8080" in raw, "gcloud run deploy must include --port=8080"


# ---------------------------------------------------------------------------
# Backend workflow — --set-secrets with all 6 secrets (requires task 5 updates)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_deploy_set_secrets_google_ai_api_key():
    """Req 7.3 — --set-secrets maps GOOGLE_AI_API_KEY=google-ai-api-key:latest"""
    raw = load_workflow_raw("deploy-backend.yml")
    assert "GOOGLE_AI_API_KEY=google-ai-api-key:latest" in raw


@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_deploy_set_secrets_llama_cloud_api_key():
    """Req 7.3 — --set-secrets maps LLAMA_CLOUD_API_KEY=llama-cloud-api-key:latest"""
    raw = load_workflow_raw("deploy-backend.yml")
    assert "LLAMA_CLOUD_API_KEY=llama-cloud-api-key:latest" in raw


@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_deploy_set_secrets_alloydb_instance_uri():
    """Req 7.3 — --set-secrets maps ALLOYDB_INSTANCE_URI=alloydb-instance-uri:latest"""
    raw = load_workflow_raw("deploy-backend.yml")
    assert "ALLOYDB_INSTANCE_URI=alloydb-instance-uri:latest" in raw


@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_deploy_set_secrets_db_user():
    """Req 7.3 — --set-secrets maps DB_USER=db-user:latest"""
    raw = load_workflow_raw("deploy-backend.yml")
    assert "DB_USER=db-user:latest" in raw


@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_deploy_set_secrets_db_pass():
    """Req 7.3 — --set-secrets maps DB_PASS=db-pass:latest"""
    raw = load_workflow_raw("deploy-backend.yml")
    assert "DB_PASS=db-pass:latest" in raw


@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_deploy_set_secrets_db_name():
    """Req 7.3 — --set-secrets maps DB_NAME=db-name:latest"""
    raw = load_workflow_raw("deploy-backend.yml")
    assert "DB_NAME=db-name:latest" in raw


# ---------------------------------------------------------------------------
# Backend workflow — smoke test (requires task 5 updates)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_smoke_test_uses_brace_expansion():
    """Req 8.2 — smoke test uses {1..5} brace expansion for retry loop"""
    raw = load_workflow_raw("deploy-backend.yml")
    assert "{1..5}" in raw, "Smoke test must use '{1..5}' brace expansion"


@pytest.mark.xfail(strict=False, reason="Requires task 5 to update deploy-backend.yml")
def test_backend_smoke_test_has_sleep_10():
    """Req 8.2 — smoke test sleeps 10 seconds between attempts"""
    raw = load_workflow_raw("deploy-backend.yml")
    assert "sleep 10" in raw, "Smoke test must use 'sleep 10' between attempts"


# ---------------------------------------------------------------------------
# Frontend workflow — trigger (requires task 6 to create deploy-frontend.yml)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_workflow_file_exists():
    """Req 9.1 — deploy-frontend.yml exists"""
    assert (WORKFLOWS_DIR / "deploy-frontend.yml").exists()


@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_workflow_trigger_paths_includes_frontend():
    """Req 9.1 — push trigger paths includes frontend/**"""
    data = load_workflow_yaml("deploy-frontend.yml")
    trigger = data.get("on") or data.get(True)
    paths = trigger["push"]["paths"]
    assert "frontend/**" in paths


# ---------------------------------------------------------------------------
# Frontend workflow — permissions (requires task 6)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_workflow_permissions_pages_write():
    """Req 10.3 — permissions block has pages: write"""
    data = load_workflow_yaml("deploy-frontend.yml")
    perms = data.get("permissions", {})
    assert perms.get("pages") == "write"


@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_workflow_permissions_id_token_write():
    """Req 10.3 — permissions block has id-token: write"""
    data = load_workflow_yaml("deploy-frontend.yml")
    perms = data.get("permissions", {})
    assert perms.get("id-token") == "write"


# ---------------------------------------------------------------------------
# Frontend workflow — concurrency (requires task 6)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_workflow_concurrency_group_pages():
    """Req 10.4 — concurrency group is 'pages'"""
    data = load_workflow_yaml("deploy-frontend.yml")
    concurrency = data.get("concurrency", {})
    assert concurrency.get("group") == "pages"


@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_workflow_concurrency_cancel_in_progress():
    """Req 10.4 — concurrency cancel-in-progress: true"""
    data = load_workflow_yaml("deploy-frontend.yml")
    concurrency = data.get("concurrency", {})
    assert concurrency.get("cancel-in-progress") is True


# ---------------------------------------------------------------------------
# Frontend workflow — build job (requires task 6)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_build_job_uses_node_20():
    """Req 9.5 — build job uses Node 20"""
    data = load_workflow_yaml("deploy-frontend.yml")
    steps = data["jobs"]["build"]["steps"]
    node_versions = [
        str(s.get("with", {}).get("node-version", ""))
        for s in steps
        if "node-version" in (s.get("with") or {})
    ]
    assert any("20" in v for v in node_versions), (
        f"Node 20 not found in build job steps, got: {node_versions}"
    )


@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_build_job_caches_with_package_lock():
    """Req 9.5 — build job caches npm deps using frontend/package-lock.json"""
    raw = load_workflow_raw("deploy-frontend.yml")
    assert "frontend/package-lock.json" in raw, (
        "build job must cache using frontend/package-lock.json"
    )


@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_build_job_step_npm_ci():
    """Req 9.2 — build job includes npm ci step"""
    data = load_workflow_yaml("deploy-frontend.yml")
    steps = data["jobs"]["build"]["steps"]
    run_commands = [s.get("run", "") for s in steps]
    assert any("npm ci" in cmd for cmd in run_commands), "build job must have npm ci step"


@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_build_job_step_npm_test_run():
    """Req 9.2 — build job includes npm test -- --run step"""
    data = load_workflow_yaml("deploy-frontend.yml")
    steps = data["jobs"]["build"]["steps"]
    run_commands = [s.get("run", "") for s in steps]
    assert any("npm test" in cmd for cmd in run_commands), "build job must have npm test step"
    assert any("--run" in cmd for cmd in run_commands), "npm test must use --run flag"


@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_build_job_step_npm_run_build():
    """Req 9.4 — build job includes npm run build step"""
    data = load_workflow_yaml("deploy-frontend.yml")
    steps = data["jobs"]["build"]["steps"]
    run_commands = [s.get("run", "") for s in steps]
    assert any("npm run build" in cmd for cmd in run_commands), (
        "build job must have npm run build step"
    )


@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_build_job_sets_vite_api_base_secret():
    """Req 9.4 — build step sets VITE_API_BASE from secrets.VITE_API_BASE"""
    raw = load_workflow_raw("deploy-frontend.yml")
    assert "VITE_API_BASE" in raw, "build job must reference VITE_API_BASE"
    assert "secrets.VITE_API_BASE" in raw, (
        "VITE_API_BASE must be set from secrets.VITE_API_BASE"
    )


@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_build_job_uploads_pages_artifact_v3():
    """Req 10.1 — build job uses actions/upload-pages-artifact@v3"""
    data = load_workflow_yaml("deploy-frontend.yml")
    steps = data["jobs"]["build"]["steps"]
    uses_values = [s.get("uses", "") for s in steps]
    assert any("actions/upload-pages-artifact@v3" in u for u in uses_values), (
        "build job must use actions/upload-pages-artifact@v3"
    )


@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_build_job_artifact_path_is_frontend_dist():
    """Req 10.1 — upload-pages-artifact uses path: frontend/dist"""
    data = load_workflow_yaml("deploy-frontend.yml")
    steps = data["jobs"]["build"]["steps"]
    for step in steps:
        if "upload-pages-artifact" in (step.get("uses") or ""):
            with_block = step.get("with") or {}
            assert with_block.get("path") == "frontend/dist", (
                f"upload-pages-artifact path must be 'frontend/dist', got: {with_block.get('path')}"
            )
            return
    pytest.fail("upload-pages-artifact step not found in build job")


# ---------------------------------------------------------------------------
# Frontend workflow — deploy job (requires task 6)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=False, reason="Requires task 6 to create deploy-frontend.yml")
def test_frontend_deploy_job_uses_deploy_pages_v4():
    """Req 10.2 — deploy job uses actions/deploy-pages@v4"""
    data = load_workflow_yaml("deploy-frontend.yml")
    steps = data["jobs"]["deploy"]["steps"]
    uses_values = [s.get("uses", "") for s in steps]
    assert any("actions/deploy-pages@v4" in u for u in uses_values), (
        "deploy job must use actions/deploy-pages@v4"
    )


# ---------------------------------------------------------------------------
# Vite config — base path
# ---------------------------------------------------------------------------

def test_vite_config_base_path():
    """Req 11.1 — frontend/vite.config.js contains base: '/BRD_Analyzer/'"""
    vite_config = (REPO_ROOT / "frontend" / "vite.config.js").read_text()
    assert "base: '/BRD_Analyzer/'" in vite_config, (
        "vite.config.js must contain base: '/BRD_Analyzer/'"
    )


# ---------------------------------------------------------------------------
# CORS — ALLOWED_ORIGINS in requirement_summarizer_app.py
# ---------------------------------------------------------------------------

def test_cors_allows_github_pages_origin():
    """Req 12.1 — ALLOWED_ORIGINS includes https://sayan1320.github.io"""
    app_src = (REPO_ROOT / "backend" / "requirement_summarizer_app.py").read_text()
    assert "https://sayan1320.github.io" in app_src, (
        "ALLOWED_ORIGINS must include https://sayan1320.github.io"
    )


def test_cors_allows_localhost_5173():
    """Req 12.2 — ALLOWED_ORIGINS includes http://localhost:5173"""
    app_src = (REPO_ROOT / "backend" / "requirement_summarizer_app.py").read_text()
    assert "http://localhost:5173" in app_src, (
        "ALLOWED_ORIGINS must include http://localhost:5173"
    )


def test_cors_allows_localhost_3000():
    """Req 12.2 — ALLOWED_ORIGINS includes http://localhost:3000"""
    app_src = (REPO_ROOT / "backend" / "requirement_summarizer_app.py").read_text()
    assert "http://localhost:3000" in app_src, (
        "ALLOWED_ORIGINS must include http://localhost:3000"
    )


# ---------------------------------------------------------------------------
# .gitignore — credential patterns (Req 13.1)
# ---------------------------------------------------------------------------

def _gitignore_lines() -> list[str]:
    return (REPO_ROOT / ".gitignore").read_text().splitlines()


def test_gitignore_has_env():
    """Req 13.1 — .gitignore contains .env"""
    assert ".env" in _gitignore_lines()


def test_gitignore_has_env_wildcard():
    """Req 13.1 — .gitignore contains .env.*"""
    assert ".env.*" in _gitignore_lines()


def test_gitignore_has_env_example_negation():
    """Req 13.1 — .gitignore contains !.env.example"""
    assert "!.env.example" in _gitignore_lines()


def test_gitignore_has_json_key_wildcard():
    """Req 13.1 — .gitignore contains *.json.key"""
    assert "*.json.key" in _gitignore_lines()


def test_gitignore_has_github_ci_key():
    """Req 13.1 — .gitignore contains github-ci-key.json"""
    assert "github-ci-key.json" in _gitignore_lines()


def test_gitignore_has_application_default_credentials():
    """Req 13.1 — .gitignore contains application_default_credentials.json"""
    assert "application_default_credentials.json" in _gitignore_lines()


def test_gitignore_has_service_account_wildcard():
    """Req 13.1 — .gitignore contains *-service-account*.json"""
    assert "*-service-account*.json" in _gitignore_lines()


# ---------------------------------------------------------------------------
# .gitignore — build artifact patterns (Req 13.2)
# ---------------------------------------------------------------------------

def test_gitignore_has_node_modules():
    """Req 13.2 — .gitignore contains node_modules/"""
    assert "node_modules/" in _gitignore_lines()


def test_gitignore_has_frontend_dist():
    """Req 13.2 — .gitignore contains frontend/dist/"""
    assert "frontend/dist/" in _gitignore_lines()


def test_gitignore_has_pycache():
    """Req 13.2 — .gitignore contains __pycache__/"""
    assert "__pycache__/" in _gitignore_lines()


def test_gitignore_has_pytest_cache():
    """Req 13.2 — .gitignore contains .pytest_cache/"""
    assert ".pytest_cache/" in _gitignore_lines()


def test_gitignore_has_venv():
    """Req 13.2 — .gitignore contains .venv/"""
    assert ".venv/" in _gitignore_lines()
