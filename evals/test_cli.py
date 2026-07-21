"""
Unit tests for Phase 22 Packaging as an Installable Tool (sre-agent CLI).
"""
import sys
from pathlib import Path
import pytest
import yaml

from agent.cli import init_command, main


def test_sre_agent_init_scaffolding(tmp_path):
    """Verify sre-agent init scaffolds sre-agent.yaml pre-filled with repo profile."""
    repo_dir = tmp_path / "custom-app"
    repo_dir.mkdir()

    # Create Dockerfile with uvicorn entrypoint
    (repo_dir / "Dockerfile").write_text("CMD [\"uvicorn\", \"custom_app.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"9000\"]")

    config_path = init_command(repo_dir)

    assert config_path.exists()
    assert config_path.name == "sre-agent.yaml"

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert data["service_name"] == "custom-app"
    assert data["language"] == "python"
    assert "uvicorn" in data["entrypoint"]


def test_sre_agent_cli_parser(monkeypatch, capsys):
    """Verify CLI argument parsing for sre-agent --help."""
    monkeypatch.setattr(sys, "argv", ["sre-agent", "--help"])

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "Autonomous SRE Incident-Triage Agent CLI" in captured.out
    assert "init" in captured.out
    assert "run" in captured.out
    assert "webhook" in captured.out
