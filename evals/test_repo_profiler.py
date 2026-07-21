"""
Unit tests for Phase 15 Repo Profiler / Introspection Subagent.
"""
from pathlib import Path
import pytest
from agent.config import SREAgentConfig
from agent.subagents.repo_profiler import profile_repository


PROJECT_ROOT = Path(__file__).parent.parent


def test_profile_breakomatic_repo():
    """Verify repo profiler correctly profiles breakomatic repository with sre-agent.yaml."""
    profile = profile_repository(PROJECT_ROOT)

    assert isinstance(profile, SREAgentConfig)
    assert profile.service_name == "breakomatic"
    assert profile.language == "python"
    assert profile.framework == "fastapi"
    assert "uvicorn" in profile.entrypoint
    assert profile.log_source == "/tmp/breakomatic.log"


def test_profile_unfamiliar_python_repo_without_config(tmp_path):
    """Verify repo profiler auto-detects build/run/test commands for an unfamiliar repo without sre-agent.yaml."""
    repo_dir = tmp_path / "payment-api"
    repo_dir.mkdir()

    # Create Dockerfile
    dockerfile = repo_dir / "Dockerfile"
    dockerfile.write_text("""\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "payment_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
""")

    # Create pyproject.toml
    pyproject = repo_dir / "pyproject.toml"
    pyproject.write_text("""\
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
""")

    # Create README.md
    readme = repo_dir / "README.md"
    readme.write_text("# Payment API Microservice\nRun tests with `pytest`.\n")

    profile = profile_repository(repo_dir)

    assert isinstance(profile, SREAgentConfig)
    assert profile.service_name == "payment-api"
    assert profile.language == "python"
    assert profile.framework == "fastapi"
    assert "uvicorn" in profile.entrypoint
    assert profile.test_command == "pytest"


def test_explicit_sre_agent_yaml_overrides_autodetected(tmp_path):
    """Verify explicit sre-agent.yaml file cleanly overrides auto-detected heuristics."""
    repo_dir = tmp_path / "custom-service"
    repo_dir.mkdir()

    # Create Dockerfile with uvicorn
    (repo_dir / "Dockerfile").write_text("CMD [\"uvicorn\", \"app:app\"]")

    # Create sre-agent.yaml specifying custom entrypoint and test command
    (repo_dir / "sre-agent.yaml").write_text("""\
service_name: "custom-service"
entrypoint: "gunicorn app:app -b 0.0.0.0:8000"
test_command: "python -m unittest discover"
""")

    profile = profile_repository(repo_dir)

    assert profile.service_name == "custom-service"
    assert profile.entrypoint == "gunicorn app:app -b 0.0.0.0:8000"
    assert profile.test_command == "python -m unittest discover"
