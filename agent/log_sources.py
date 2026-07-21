"""
Pluggable Log & Observability Adapters for SRE Agent.

Provides a unified LogSource interface with implementations for:
- LocalFileLogSource (tailing local/container log files)
- DatadogLogSource (Datadog Logs v2 Search API)
- CloudWatchLogSource (AWS CloudWatch Logs API)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import json
import os
from pathlib import Path
from typing import Any, Optional
import urllib.request
import urllib.error


class LogSource(ABC):
    """Abstract interface for pluggable log/observability sources."""

    @abstractmethod
    def fetch_logs(self, query: str = "", limit: int = 100) -> list[str]:
        """Fetch log entries matching query up to specified limit."""
        pass


class LocalFileLogSource(LogSource):
    """LogSource adapter for local files or mounted container logs."""

    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)

    def fetch_logs(self, query: str = "", limit: int = 100) -> list[str]:
        if not self.log_path.exists():
            return [f"Log file not found at: {self.log_path}"]

        try:
            lines = self.log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if query:
                lines = [line for line in lines if query.lower() in line.lower()]
            return lines[-limit:]
        except Exception as e:
            return [f"Error reading log file {self.log_path}: {e}"]


class DatadogLogSource(LogSource):
    """LogSource adapter for Datadog Logs v2 Search API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        app_key: Optional[str] = None,
        site: str = "datadoghq.com",
    ):
        self.api_key = api_key or os.environ.get("DD_API_KEY", "")
        self.app_key = app_key or os.environ.get("DD_APP_KEY", "")
        self.site = site

    def fetch_logs(self, query: str = "", limit: int = 100) -> list[str]:
        if not self.api_key:
            return [f"[DatadogLogSource Mock] Query '{query}' returned 0 live logs (DD_API_KEY not set)."]

        url = f"https://api.{self.site}/api/v2/logs/events/search"
        payload = {
            "filter": {
                "query": query or "*",
                "from": "now-15m",
                "to": "now",
            },
            "page": {"limit": min(limit, 1000)},
        }

        headers = {
            "Content-Type": "application/json",
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key,
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                events = data.get("data", [])
                logs = []
                for ev in events:
                    attrs = ev.get("attributes", {})
                    msg = attrs.get("message") or json.dumps(attrs)
                    logs.append(msg)
                return logs
        except urllib.error.HTTPError as e:
            return [f"Datadog API Error {e.code}: {e.reason}"]
        except Exception as e:
            return [f"Datadog connection error: {e}"]


class CloudWatchLogSource(LogSource):
    """LogSource adapter for AWS CloudWatch Logs."""

    def __init__(self, log_group: str, region: str = "us-east-1"):
        self.log_group = log_group
        self.region = region

    def fetch_logs(self, query: str = "", limit: int = 100) -> list[str]:
        # Graceful fallback if boto3 is not installed or AWS credentials missing
        try:
            import boto3
            client = boto3.client("logs", region_name=self.region)
            kwargs: dict[str, Any] = {
                "logGroupName": self.log_group,
                "limit": limit,
            }
            if query:
                kwargs["filterPattern"] = query
            response = client.filter_log_events(**kwargs)
            return [ev["message"] for ev in response.get("events", [])]
        except Exception as e:
            return [f"[CloudWatchLogSource ({self.log_group})] {e}"]


def get_log_source(source_spec: str | Path | dict[str, Any]) -> LogSource:
    """Factory function instantiating the appropriate LogSource adapter based on configuration."""
    if isinstance(source_spec, dict):
        stype = source_spec.get("type", "local").lower()
        if stype == "datadog":
            return DatadogLogSource(
                api_key=source_spec.get("api_key"),
                app_key=source_spec.get("app_key"),
                site=source_spec.get("site", "datadoghq.com"),
            )
        elif stype == "cloudwatch":
            return CloudWatchLogSource(
                log_group=source_spec.get("log_group", "/aws/lambda/service"),
                region=source_spec.get("region", "us-east-1"),
            )
        else:
            return LocalFileLogSource(source_spec.get("path", "/tmp/app.log"))

    spec_str = str(source_spec)
    if spec_str.startswith("datadog://") or spec_str.lower() == "datadog":
        return DatadogLogSource()
    elif spec_str.startswith("cloudwatch://"):
        group = spec_str.replace("cloudwatch://", "")
        return CloudWatchLogSource(log_group=group)
    else:
        return LocalFileLogSource(spec_str)
