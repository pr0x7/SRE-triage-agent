"""
Log Analyzer subagent spec and runner.
Parses stack traces, logs from pluggable LogSource adapters, and incident artifacts to form hypotheses.
"""
from __future__ import annotations

import os
from typing import Optional
from langchain_core.messages import SystemMessage, HumanMessage
from agent.llm import ChatGroqWithRetry
from agent.log_sources import LogSource, get_log_source

SYSTEM_PROMPT = """\
You are an SRE specialist in log analysis and crash diagnosis.
Your task is to analyze the provided incident report and fetched log entries (from the configured LogSource adapter) \
and identify the likely root cause.

Please provide your diagnosis in the following structure:
1. **Summary**: A clear, one-sentence summary of the failure.
2. **Error Analysis**: Details of the exact exception, message, and file/line where it occurred.
3. **Log Correlation**: Any correlation found between the log events and the crash.
4. **Hypothesis**: The proposed root cause (e.g. N+1 query, Null Dereference, Leaked Connection, etc.) \
and the reasoning behind it.
"""


def run_log_analyzer(
    incident_context: str,
    log_source: Optional[LogSource | str] = None,
) -> str:
    """Run the log-analyzer subagent against a generic LogSource interface.

    Args:
        incident_context: Stack trace, logs, or metrics string.
        log_source: Optional LogSource instance or log source specification string.
    """
    if log_source is None:
        source_adapter = get_log_source("/tmp/breakomatic.log")
    elif isinstance(log_source, str):
        source_adapter = get_log_source(log_source)
    else:
        source_adapter = log_source

    fetched_logs = source_adapter.fetch_logs(limit=50)
    fetched_str = "\n".join(fetched_logs) if fetched_logs else "No external logs retrieved."

    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    llm = ChatGroqWithRetry(
        model="llama-3.3-70b-versatile",
        api_key=groq_api_key,
        temperature=0.0,
        max_tool_retries=3,
    )

    combined_context = (
        f"Incident Context:\n{incident_context}\n\n"
        f"--- LogSource Adapter Output ({source_adapter.__class__.__name__}) ---\n"
        f"{fetched_str}"
    )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=combined_context),
    ]
    response = llm.invoke(messages)
    return response.content
