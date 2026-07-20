"""
Log Analyzer subagent spec and runner.
Parses stack traces, logs, and other incident artifacts to form hypotheses.
"""
from __future__ import annotations

import os
from langchain_core.messages import SystemMessage, HumanMessage
from agent.llm import ChatGroqWithRetry

SYSTEM_PROMPT = """\
You are an SRE specialist in log analysis and crash diagnosis.
Your task is to analyze the provided incident report (which includes a stack trace, \
log dump, recent deployment messages, and metrics) and identify the likely root cause.

Please provide your diagnosis in the following structure:
1. **Summary**: A clear, one-sentence summary of the failure.
2. **Error Analysis**: Details of the exact exception, message, and file/line where it occurred.
3. **Log Correlation**: Any correlation found between the log events and the crash.
4. **Hypothesis**: The proposed root cause (e.g. N+1 query, Null Dereference, Leaked Connection, etc.) \
and the reasoning behind it.
"""


def run_log_analyzer(incident_context: str) -> str:
    """Run the log-analyzer subagent to parse logs and tracebacks."""
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
