"""
Real Incident Ingestion & Webhook Normalizer Module.

Normalizes incoming webhook payloads from alerting providers (Sentry, PagerDuty, Datadog)
into the agent's internal incident payload schema.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def parse_sentry_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Sentry Issue/Event Webhook payload into internal incident schema."""
    data = payload.get("data", {})
    issue = data.get("issue", {})
    event = data.get("event", {})

    incident_id = f"SENTRY-{issue.get('id') or event.get('event_id', '001')}"
    title = issue.get("title") or payload.get("message") or "Sentry Exception Alert"
    service = issue.get("project", {}).get("slug") or payload.get("project_slug") or "unknown-service"

    level = event.get("level") or payload.get("level") or "error"
    severity = "P1" if level in ("fatal", "error") else "P2"
    timestamp = issue.get("firstSeen") or datetime.now(timezone.utc).isoformat()

    # Extract stack trace details
    stack_trace = ""
    culprit = issue.get("culprit") or event.get("culprit")
    if culprit:
        stack_trace += f"Culprit: {culprit}\n"

    entries = event.get("entries", [])
    for entry in entries:
        if entry.get("type") == "exception":
            values = entry.get("data", {}).get("values", [])
            for val in values:
                exc_type = val.get("type", "Exception")
                exc_value = val.get("value", "")
                stack_trace += f"{exc_type}: {exc_value}\n"
                frames = val.get("stacktrace", {}).get("frames", [])
                for frame in frames[-5:]:
                    fn = frame.get("filename") or frame.get("abs_path")
                    line = frame.get("lineno")
                    func = frame.get("function")
                    stack_trace += f"  File \"{fn}\", line {line}, in {func}\n"

    if not stack_trace:
        stack_trace = f"Sentry Alert: {title}\nNo raw stacktrace frames present in event payload."

    tags = event.get("tags", [])
    tag_logs = [f"{t[0]}={t[1]}" for t in tags if isinstance(t, (list, tuple)) and len(t) == 2]

    return {
        "incident_id": incident_id,
        "title": title,
        "service": service,
        "severity": severity,
        "timestamp": timestamp,
        "stack_trace": stack_trace,
        "logs": tag_logs or [f"Sentry issue ID: {issue.get('id')}"],
        "recent_deploys": [],
        "metrics": {"sentry_count": issue.get("count", 1)},
    }


def parse_pagerduty_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Parse PagerDuty Webhook v3 payload into internal incident schema."""
    event = payload.get("event", {})
    data = event.get("data", {})

    incident_id = f"PD-{data.get('id') or data.get('number', '001')}"
    title = data.get("title") or event.get("event_type") or "PagerDuty Incident Alert"
    service = data.get("service", {}).get("summary") or "production-service"

    urgency = data.get("urgency", "high")
    severity = "P1" if urgency == "high" else "P2"
    timestamp = data.get("created_at") or datetime.now(timezone.utc).isoformat()

    body_details = data.get("body", {}).get("details") or {}
    stack_trace = f"PagerDuty Incident: {title}\nDetails: {body_details}"

    return {
        "incident_id": incident_id,
        "title": title,
        "service": service,
        "severity": severity,
        "timestamp": timestamp,
        "stack_trace": stack_trace,
        "logs": [f"PagerDuty Status: {data.get('status', 'triggered')}"],
        "recent_deploys": [],
        "metrics": {"urgency": urgency},
    }


def parse_datadog_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Datadog Alert Webhook payload into internal incident schema."""
    incident_id = f"DD-{payload.get('id') or '001'}"
    title = payload.get("event_title") or payload.get("title") or "Datadog Monitor Triggered"
    service = payload.get("service") or payload.get("tags", {}).get("service") if isinstance(payload.get("tags"), dict) else "monitored-service"

    alert_type = payload.get("alert_type", "error")
    severity = "P1" if alert_type == "error" else "P2"
    timestamp = datetime.now(timezone.utc).isoformat()

    stack_trace = f"Datadog Alert: {title}\nMetric Query: {payload.get('alert_query', 'N/A')}\nText: {payload.get('body', '')}"

    return {
        "incident_id": incident_id,
        "title": title,
        "service": service,
        "severity": severity,
        "timestamp": timestamp,
        "stack_trace": stack_trace,
        "logs": [f"Datadog Event Transition: {payload.get('transition', 'TRIGGERED')}"],
        "recent_deploys": [],
        "metrics": {
            "alert_metric": payload.get("alert_metric", "unknown"),
            "value": payload.get("value"),
        },
    }


def normalize_webhook_payload(provider: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Unified normalizer transforming external webhook payloads to internal schema."""
    provider_clean = provider.strip().lower()

    if provider_clean == "sentry":
        normalized = parse_sentry_webhook(payload)
    elif provider_clean == "pagerduty":
        normalized = parse_pagerduty_webhook(payload)
    elif provider_clean == "datadog":
        normalized = parse_datadog_webhook(payload)
    else:
        # Generic payload fallback
        normalized = {
            "incident_id": payload.get("id") or payload.get("incident_id") or "INC-GENERIC-001",
            "title": payload.get("title") or payload.get("message") or f"Generic {provider} Alert",
            "service": payload.get("service") or "unknown-service",
            "severity": payload.get("severity") or "P2",
            "timestamp": payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "stack_trace": payload.get("stack_trace") or str(payload),
            "logs": payload.get("logs") or [],
            "recent_deploys": payload.get("recent_deploys") or [],
            "metrics": payload.get("metrics") or {},
        }

    # Ensure required schema fields exist with safe defaults
    defaults = {
        "incident_id": "INC-000",
        "title": "Incident Alert",
        "service": "unknown-service",
        "severity": "P2",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stack_trace": "",
        "logs": [],
        "recent_deploys": [],
        "metrics": {},
    }

    for k, v in defaults.items():
        if k not in normalized or normalized[k] is None:
            normalized[k] = v

    return normalized
