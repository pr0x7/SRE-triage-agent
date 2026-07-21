"""
Unit tests for Phase 18 Real Incident Ingestion & Webhook Receivers.
"""
from fastapi.testclient import TestClient
import pytest
from agent.ingestion import (
    parse_sentry_webhook,
    parse_pagerduty_webhook,
    parse_datadog_webhook,
    normalize_webhook_payload,
)
from scripts.webhook_receiver import app


client = TestClient(app)


def test_parse_sentry_webhook():
    """Verify Sentry webhook normalization."""
    sentry_payload = {
        "project_slug": "user-service",
        "level": "error",
        "data": {
            "issue": {
                "id": "98765",
                "title": "AttributeError: 'NoneType' object has no attribute 'profile'",
                "culprit": "app.services.user:get_profile",
                "firstSeen": "2026-07-21T19:00:00Z",
                "count": 42,
            },
            "event": {
                "event_id": "abc123evt",
                "entries": [
                    {
                        "type": "exception",
                        "data": {
                            "values": [
                                {
                                    "type": "AttributeError",
                                    "value": "'NoneType' object has no attribute 'profile'",
                                    "stacktrace": {
                                        "frames": [
                                            {
                                                "filename": "app/services/user.py",
                                                "lineno": 45,
                                                "function": "get_profile",
                                            }
                                        ]
                                    },
                                }
                            ]
                        },
                    }
                ],
                "tags": [["environment", "production"], ["level", "error"]],
            },
        },
    }

    normalized = parse_sentry_webhook(sentry_payload)

    assert normalized["incident_id"] == "SENTRY-98765"
    assert "AttributeError" in normalized["title"]
    assert normalized["severity"] == "P1"
    assert "Culprit: app.services.user:get_profile" in normalized["stack_trace"]
    assert "app/services/user.py" in normalized["stack_trace"]


def test_parse_pagerduty_webhook():
    """Verify PagerDuty webhook normalization."""
    pd_payload = {
        "event": {
            "event_type": "incident.triggered",
            "data": {
                "id": "PD-INC-123",
                "title": "High Latency in Orders Endpoint",
                "status": "triggered",
                "urgency": "high",
                "created_at": "2026-07-21T19:15:00Z",
                "service": {"summary": "orders-api"},
                "body": {"details": {"latency_p99": "4500ms"}},
            },
        }
    }

    normalized = parse_pagerduty_webhook(pd_payload)

    assert normalized["incident_id"] == "PD-PD-INC-123"
    assert normalized["title"] == "High Latency in Orders Endpoint"
    assert normalized["service"] == "orders-api"
    assert normalized["severity"] == "P1"
    assert "4500ms" in normalized["stack_trace"]


def test_parse_datadog_webhook():
    """Verify Datadog webhook normalization."""
    dd_payload = {
        "id": "DD-MON-444",
        "event_title": "[Triggered] Database Connection Pool Exhausted",
        "alert_type": "error",
        "service": "database-proxy",
        "alert_query": "avg(last_5m):sum:db.connections{*} > 95",
        "value": 98.5,
    }

    normalized = parse_datadog_webhook(dd_payload)

    assert normalized["incident_id"] == "DD-DD-MON-444"
    assert "Database Connection Pool Exhausted" in normalized["title"]
    assert normalized["severity"] == "P1"
    assert normalized["metrics"]["value"] == 98.5


def test_webhook_receiver_http_endpoints():
    """Verify FastAPI TestClient POST /webhook/{provider} endpoints."""
    # Test GET /health
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.json()["status"] == "ok"

    # Test POST /webhook/sentry?dry_run=true
    resp_sentry = client.post(
        "/webhook/sentry?dry_run=true",
        json={"data": {"issue": {"id": "111", "title": "Test Sentry Alert"}}},
    )
    assert resp_sentry.status_code == 200
    assert resp_sentry.json()["status"] == "accepted"
    assert resp_sentry.json()["incident_id"] == "SENTRY-111"

    # Test POST /webhook/pagerduty?dry_run=true
    resp_pd = client.post(
        "/webhook/pagerduty?dry_run=true",
        json={"event": {"data": {"id": "222", "title": "Test PagerDuty Alert"}}},
    )
    assert resp_pd.status_code == 200
    assert resp_pd.json()["incident_id"] == "PD-222"

    # Test POST /webhook/datadog?dry_run=true
    resp_dd = client.post(
        "/webhook/datadog?dry_run=true",
        json={"id": "333", "event_title": "Test Datadog Alert"},
    )
    assert resp_dd.status_code == 200
    assert resp_dd.json()["incident_id"] == "DD-333"
