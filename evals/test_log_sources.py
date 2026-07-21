"""
Unit tests for Phase 16 Pluggable Log/Observability Adapters.
"""
from pathlib import Path
import pytest
from agent.log_sources import (
    LogSource,
    LocalFileLogSource,
    DatadogLogSource,
    CloudWatchLogSource,
    get_log_source,
)


class MockLogSource(LogSource):
    """Custom mock LogSource for testing log_analyzer integration."""

    def __init__(self, log_lines: list[str]):
        self.log_lines = log_lines

    def fetch_logs(self, query: str = "", limit: int = 100) -> list[str]:
        if query:
            return [line for line in self.log_lines if query.lower() in line.lower()][:limit]
        return self.log_lines[:limit]


def test_local_file_log_source(tmp_path):
    """Verify LocalFileLogSource reads and filters log files."""
    log_file = tmp_path / "test_app.log"
    log_file.write_text("INFO Service started\nERROR Database connection failed\nINFO Retrying connection\n")

    source = LocalFileLogSource(log_file)
    all_logs = source.fetch_logs(limit=10)
    assert len(all_logs) == 3
    assert "ERROR Database connection failed" in all_logs[1]

    filtered_logs = source.fetch_logs(query="ERROR", limit=10)
    assert len(filtered_logs) == 1
    assert "Database connection failed" in filtered_logs[0]


def test_local_file_log_source_missing_file(tmp_path):
    """Verify LocalFileLogSource returns informative message for missing file."""
    source = LocalFileLogSource(tmp_path / "non_existent.log")
    logs = source.fetch_logs()
    assert len(logs) == 1
    assert "Log file not found" in logs[0]


def test_datadog_log_source_initialization():
    """Verify DatadogLogSource adapter initialization and API spec handling."""
    dd = DatadogLogSource(api_key="test_api_key", app_key="test_app_key", site="datadoghq.eu")
    assert dd.api_key == "test_api_key"
    assert dd.site == "datadoghq.eu"

    # With no API key set
    dd_empty = DatadogLogSource(api_key="")
    logs = dd_empty.fetch_logs(query="service:payment")
    assert len(logs) == 1
    assert "DD_API_KEY not set" in logs[0]


def test_cloudwatch_log_source_initialization():
    """Verify CloudWatchLogSource adapter initialization and spec handling."""
    cw = CloudWatchLogSource(log_group="/aws/lambda/payment-service", region="us-west-2")
    assert cw.log_group == "/aws/lambda/payment-service"
    assert cw.region == "us-west-2"

    logs = cw.fetch_logs(query="Exception")
    assert isinstance(logs, list)


def test_get_log_source_factory():
    """Verify get_log_source factory instantiates correct LogSource implementations."""
    # String paths -> LocalFileLogSource
    source_file = get_log_source("/var/log/app.log")
    assert isinstance(source_file, LocalFileLogSource)

    # datadog:// URI or 'datadog' string -> DatadogLogSource
    source_dd = get_log_source("datadog")
    assert isinstance(source_dd, DatadogLogSource)

    # cloudwatch:// URI -> CloudWatchLogSource
    source_cw = get_log_source("cloudwatch:///aws/ecs/payment")
    assert isinstance(source_cw, CloudWatchLogSource)

    # Dict spec -> DatadogLogSource
    source_dict = get_log_source({"type": "datadog", "api_key": "abc"})
    assert isinstance(source_dict, DatadogLogSource)
    assert source_dict.api_key == "abc"


def test_mock_log_source_interface():
    """Verify log_analyzer can work against any custom LogSource implementation."""
    mock_source = MockLogSource([
        "2026-07-21 19:00:00 [ERROR] NullPointerException in User Profile Service",
        "2026-07-21 19:00:01 [WARN] Connection retry attempt 1",
    ])

    logs = mock_source.fetch_logs(query="NullPointer")
    assert len(logs) == 1
    assert "NullPointerException" in logs[0]
