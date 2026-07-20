"""
APM Analyzer subagent spec and runner.
Analyzes Datadog-like metrics and trace outputs for performance issues.
"""
from __future__ import annotations

import os
from langchain_core.messages import SystemMessage, HumanMessage
from agent.llm import ChatGroqWithRetry

SYSTEM_PROMPT = """\
You are an SRE specialist in Application Performance Monitoring (APM).
Your task is to analyze the provided incident report, specifically focusing on the Metrics section (mocked Datadog outputs) and any latency/throughput patterns.

Please provide your diagnosis in the following structure:
1. **Metrics Summary**: A summary of key metric anomalies (e.g., latency spikes, error rate jumps).
2. **Resource Saturation**: Identify if any connections, CPU, or memory are maxed out based on the metrics.
3. **Hypothesis**: The proposed root cause (e.g. N+1 query, Leaked Connection, etc.) and the reasoning behind it based purely on performance indicators.
"""


def run_apm_analyzer(incident_context: str) -> str:
    """Run the apm-analyzer subagent to parse metrics and APM data."""
    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    llm = ChatGroqWithRetry(
        model="llama-3.3-70b-versatile",
        api_key=groq_api_key,
        temperature=0.0,
        max_tool_retries=3,
    )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Incident Context:\n{incident_context}"),
    ]
    response = llm.invoke(messages)
    return response.content
