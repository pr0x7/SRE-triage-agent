"""
Memory — AGENTS.md + Store wiring for incident pattern memory.

Implementation: Phase 9
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from agent.llm import ChatGroqWithRetry

logger = logging.getLogger(__name__)

AGENTS_MD_PATH = Path(__file__).parent.parent / "AGENTS.md"


def save_to_memory(bug_name: str, diagnosis_json: str, store: BaseStore) -> None:
    """Save resolved incident details to the LangGraph Store and append to AGENTS.md."""
    try:
        diagnosis = json.loads(diagnosis_json)
    except json.JSONDecodeError:
        diagnosis = {"error": "Failed to parse diagnosis", "raw": diagnosis_json}

    # 1. Save to programmatic Store
    logger.info(f"memory: Saving incident '{bug_name}' to Store...")
    store.put(
        ("incidents",),
        key=bug_name,
        value={
            "diagnosis": diagnosis,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "confidence": "high"
        }
    )

    # 2. Append to human-readable AGENTS.md log
    logger.info("memory: Appending to AGENTS.md...")
    log_entry = (
        f"\n## Incident: {bug_name}\n"
        f"- **Date**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"- **Root Cause**: {diagnosis.get('root_cause', 'Unknown')}\n"
        f"- **Fix**: {diagnosis.get('suggested_fix', 'Unknown')}\n"
        f"- **Confidence**: High\n"
        f"- **Summary**: {diagnosis.get('summary', '')}\n"
        f"---\n"
    )

    if not AGENTS_MD_PATH.exists():
        AGENTS_MD_PATH.write_text("# Incident Memory Log\n\nThis file tracks previously resolved incidents.\n")
    
    with AGENTS_MD_PATH.open("a") as f:
        f.write(log_entry)


def search_memory(incident_context: str, store: BaseStore) -> str | None:
    """Check past incidents to see if we've seen this exact bug before.
    Returns the bug_name if a match is found, else None.
    """
    logger.info("memory: Searching Store for past incidents...")
    past_incidents = store.search(("incidents",))
    
    if not past_incidents:
        logger.info("memory: No past incidents found in memory.")
        return None

    # Format past incidents for the LLM
    incidents_text = ""
    for item in past_incidents:
        key = item.key
        diag = item.value.get("diagnosis", {})
        incidents_text += f"\n--- PAST INCIDENT: {key} ---\n"
        incidents_text += f"Root Cause: {diag.get('root_cause', '')}\n"
        incidents_text += f"Summary: {diag.get('summary', '')}\n"
        incidents_text += f"Evidence: {diag.get('evidence', '')}\n"

    prompt = (
        f"You are the SRE Memory Agent.\n\n"
        f"We have a new incoming incident:\n"
        f"{incident_context}\n\n"
        f"We have the following PAST INCIDENTS in our memory:\n"
        f"{incidents_text}\n\n"
        f"Does the new incident EXACTLY MATCH one of the past incidents? "
        f"Look at the stack trace, error messages, and failing endpoints. "
        f"If it matches, we can skip investigation and verify the known fix.\n\n"
        f"Reply ONLY with a raw JSON object containing:\n"
        f"{{\n"
        f"  \"match_found\": true or false,\n"
        f"  \"matched_bug_name\": \"the key of the matched incident, or null\",\n"
        f"  \"reason\": \"brief justification\"\n"
        f"}}\n"
    )

    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    llm = ChatGroqWithRetry(
        model="llama-3.3-70b-versatile",
        api_key=groq_api_key,
        temperature=0.0,
        max_tool_retries=2,
    )

    messages = [
        SystemMessage(content="You determine if a new incident matches past knowledge. Output ONLY raw JSON."),
        HumanMessage(content=prompt),
    ]

    try:
        response = llm.invoke(messages)
        content = response.content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines[0].startswith("```"): lines = lines[1:]
            if lines[-1].startswith("```"): lines = lines[:-1]
            content = "\n".join(lines).strip()

        result = json.loads(content)
        if result.get("match_found") and result.get("matched_bug_name"):
            match_key = result["matched_bug_name"]
            reason = result.get("reason", "")
            logger.info(f"memory: MATCH FOUND -> {match_key} ({reason})")
            return match_key
            
    except Exception as e:
        logger.warning(f"memory: LLM memory check failed or parsing error: {e}")
        
    logger.info("memory: No exact match found.")
    return None
