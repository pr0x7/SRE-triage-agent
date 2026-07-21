#!/usr/bin/env python3
"""
FastAPI Webhook Receiver Server for Real Incident Ingestion.

Receives real-time alert webhooks from Sentry, PagerDuty, or Datadog,
normalizes them into the internal incident schema, and triggers the SRE Orchestrator agent.

Usage:
    uvicorn scripts.webhook_receiver:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.ingestion import normalize_webhook_payload

app = FastAPI(
    title="SRE Agent Webhook Receiver",
    description="Real incident ingestion server normalizing Sentry, PagerDuty, and Datadog webhooks.",
    version="1.0.0",
)


def _trigger_orchestrator(normalized_incident: Dict[str, Any]) -> None:
    """Background task to trigger the SRE Orchestrator graph on normalized incident."""
    try:
        from agent.orchestrator import create_orchestrator

        prompt = (
            f"Incident details:\n"
            f"Title: {normalized_incident.get('title')}\n"
            f"Severity: {normalized_incident.get('severity')}\n"
            f"Timestamp: {normalized_incident.get('timestamp')}\n\n"
            f"Stack Trace:\n```\n{normalized_incident.get('stack_trace')}\n```\n\n"
            f"Logs:\n" + "\n".join(normalized_incident.get("logs", []))
        )

        agent = create_orchestrator()
        config = {"configurable": {"thread_id": normalized_incident.get("incident_id", "default_thread")}}
        input_state = {
            "messages": [],
            "incident_context": prompt,
            "sandbox_id": "",
            "subagent_outputs": [],
            "selected_bug": "",
            "repro_result": "",
            "patch_result": "",
            "diagnosis": "",
            "phase": "start",
            "grader_attempts": 0,
            "grader_feedback": "",
            "approval_diff": "",
            "rejected_hypotheses": [],
            "repo_profile": {},
        }
        agent.invoke(input_state, config=config)
    except Exception as e:
        print(f"❌ Webhook trigger execution error: {e}", file=sys.stderr)


@app.get("/health")
def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "ok",
        "supported_providers": ["sentry", "pagerduty", "datadog"],
    }


@app.post("/webhook/{provider}")
async def receive_webhook(
    provider: str,
    request: Request,
    background_tasks: BackgroundTasks,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Receive, normalize, and ingest real webhook alert payload.

    Args:
        provider: Alert provider name ('sentry', 'pagerduty', 'datadog').
        request: FastAPI HTTP request containing raw webhook JSON.
        background_tasks: FastAPI background task queue.
        dry_run: If True, returns normalized JSON payload without triggering agent.
    """
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {e}")

    normalized = normalize_webhook_payload(provider, payload)

    if not dry_run:
        background_tasks.add_task(_trigger_orchestrator, normalized)

    return {
        "status": "accepted",
        "provider": provider,
        "incident_id": normalized["incident_id"],
        "normalized_incident": normalized,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("scripts.webhook_receiver:app", host="0.0.0.0", port=8000, reload=True)
