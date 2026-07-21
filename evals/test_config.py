"""
Unit tests for sre-agent.yaml schema validation and config loader.
"""
from pathlib import Path
import pytest
from agent.config import load_config, SREAgentConfig


PROJECT_ROOT = Path(__file__).parent.parent


def test_load_breakomatic_config():
    """Verify that sre-agent.yaml for breakomatic loads cleanly and validates."""
    config_path = PROJECT_ROOT / "sre-agent.yaml"
    config = load_config(config_path)

    assert isinstance(config, SREAgentConfig)
    assert config.service_name == "breakomatic"
    assert config.language == "python"
    assert config.framework == "fastapi"
    assert "uvicorn" in config.entrypoint
    assert config.test_command == "pytest evals/test_breakomatic_app.py"


def test_load_sample_external_config():
    """Verify that a hand-written config for a non-breakomatic Python repo loads cleanly."""
    sample_path = PROJECT_ROOT / "examples" / "sre-agent.sample.yaml"
    config = load_config(sample_path)

    assert isinstance(config, SREAgentConfig)
    assert config.service_name == "payment-service"
    assert config.language == "python"
    assert config.framework == "flask"
    assert config.test_command == "pytest tests/unit/"


def test_missing_config_raises_file_not_found():
    """Verify missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_config(PROJECT_ROOT / "non_existent_config.yaml")


def test_invalid_config_raises_validation_error(tmp_path):
    """Verify invalid fields raise ValueError with validation error details."""
    invalid_file = tmp_path / "bad_config.yaml"
    invalid_file.write_text("language: python\nframework: fastapi\n")  # Missing required service_name and entrypoint

    with pytest.raises(ValueError) as excinfo:
        load_config(invalid_file)

    assert "Validation error" in str(excinfo.value)
