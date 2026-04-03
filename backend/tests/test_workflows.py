"""
Workflow YAML validation tests.
Validates structural properties of GitHub Actions workflow files.
"""
import re
import yaml
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def load_yaml(filename: str) -> dict:
    path = WORKFLOWS_DIR / filename
    with open(path) as f:
        return yaml.safe_load(f)


def load_raw(filename: str) -> str:
    path = WORKFLOWS_DIR / filename
    return path.read_text()


# --- deploy-backend.yml tests ---

def test_backend_workflow_has_backend_path_filter():
    """7.1 - deploy-backend.yml has path filter for backend/**"""
    data = load_yaml("deploy-backend.yml")
    # PyYAML parses the 'on' key as boolean True (YAML reserved word)
    trigger = data.get("on") or data.get(True)
    paths = trigger["push"]["paths"]
    assert "backend/**" in paths, f"Expected 'backend/**' in paths, got: {paths}"


def test_backend_deploy_job_needs_test():
    """7.2 - deploy job in deploy-backend.yml declares needs: docker-build-verify"""
    data = load_yaml("deploy-backend.yml")
    deploy_job = data["jobs"]["deploy"]
    needs = deploy_job.get("needs", [])
    # needs can be a string or a list
    if isinstance(needs, str):
        needs = [needs]
    assert "docker-build-verify" in needs, f"Expected deploy job to need 'docker-build-verify', got needs: {needs}"


def test_backend_workflow_no_hardcoded_secrets():
    """7.3 - deploy-backend.yml contains no hardcoded secret values"""
    raw = load_raw("deploy-backend.yml")

    # Remove all ${{ secrets.X }} and ${{ github.X }} references so they don't trigger false positives
    sanitized = re.sub(r"\$\{\{[^}]+\}\}", "", raw)

    # Check for common API key patterns
    patterns = [
        (r"AIza[0-9A-Za-z\-_]{35}", "Google API key (AIza...)"),
        (r"sk-[A-Za-z0-9]{20,}", "OpenAI-style secret key (sk-...)"),
        (r"(?<![{$])[A-Za-z0-9+/]{40,}={0,2}(?![}])", "Long base64-like string (possible hardcoded secret)"),
        (r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}", "JWT token"),
    ]

    for pattern, description in patterns:
        matches = re.findall(pattern, sanitized)
        # Filter out known safe strings (e.g. Docker image paths, SHA refs, URLs)
        safe_exceptions = [
            "asia-south1-docker.pkg.dev",
            "ubuntu-latest",
            "actions/checkout",
            "actions/setup-python",
            "google-github-actions/auth",
            "peaceiris/actions-gh-pages",
        ]
        suspicious = [
            m for m in matches
            if not any(exc in m for exc in safe_exceptions)
            and len(m) >= 40
        ]
        assert not suspicious, (
            f"Possible hardcoded secret found ({description}): {suspicious}"
        )


# --- deploy-frontend.yml tests ---

def test_frontend_workflow_has_frontend_path_filter():
    """7.4 - deploy-frontend.yml has path filter for frontend/**"""
    data = load_yaml("deploy-frontend.yml")
    # PyYAML parses the 'on' key as boolean True (YAML reserved word)
    trigger = data.get("on") or data.get(True)
    paths = trigger["push"]["paths"]
    assert "frontend/**" in paths, f"Expected 'frontend/**' in paths, got: {paths}"


def test_frontend_workflow_injects_vite_api_base_from_secret():
    """7.5 - deploy-frontend.yml injects VITE_API_BASE from secrets.VITE_API_BASE"""
    raw = load_raw("deploy-frontend.yml")
    # Check the raw YAML contains the expected secret reference
    assert "VITE_API_BASE" in raw, "VITE_API_BASE not found in deploy-frontend.yml"
    assert "secrets.VITE_API_BASE" in raw, (
        "secrets.VITE_API_BASE not referenced in deploy-frontend.yml"
    )

    # Also verify via parsed YAML that VITE_API_BASE is set in a build step env
    data = load_yaml("deploy-frontend.yml")
    steps = data["jobs"]["build"]["steps"]
    vite_env_found = False
    for step in steps:
        env = step.get("env", {}) or {}
        if "VITE_API_BASE" in env:
            value = env["VITE_API_BASE"]
            assert "secrets.VITE_API_BASE" in str(value), (
                f"VITE_API_BASE should reference secrets.VITE_API_BASE, got: {value}"
            )
            vite_env_found = True
            break
    assert vite_env_found, "No step found with VITE_API_BASE env var in deploy-frontend.yml build job"
