"""
Declarative Configuration Schema and Loader for SRE Agent.

Defines the sre-agent.yaml schema for repository adapters and stack configuration.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field, ValidationError


class SREAgentConfig(BaseModel):
    """Declarative repository configuration for SRE Agent (Supported Stack v1)."""

    service_name: str = Field(..., description="Name of the service / target repo")
    language: str = Field(default="python", description="Programming language (Supported Stack v1: python)")
    framework: Optional[str] = Field(default="fastapi", description="Web framework or runtime model")
    entrypoint: str = Field(..., description="Command to start the service inside sandbox")
    build_command: str = Field(default="pip install -e .", description="Build/installation command")
    test_command: str = Field(default="pytest evals/", description="Test execution command")
    log_source: str = Field(default="/tmp/app.log", description="Path to application log file")
    db_connection_string: Optional[str] = Field(default=None, description="Read-only database connection or DB path")
    deploy_remote: Optional[str] = Field(default=None, description="Git remote or deployment tracking identifier")


def load_config(config_path: str | Path = "sre-agent.yaml") -> SREAgentConfig:
    """Load and validate an sre-agent.yaml file.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        SREAgentConfig: Validated configuration object.

    Raises:
        FileNotFoundError: If specified config path does not exist.
        ValueError: If YAML is malformed or invalid according to schema.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse YAML file {path}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Invalid config structure in {path}: expected key-value mapping")

    try:
        return SREAgentConfig(**data)
    except ValidationError as e:
        raise ValueError(f"Validation error for {path}:\n{e}") from e
