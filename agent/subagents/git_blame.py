"""
Git Blame subagent spec and runner.
Analyzes recent commits and deploys to identify potentially buggy code changes and authors.
"""
from __future__ import annotations

import os
from langchain_core.messages import SystemMessage, HumanMessage
from agent.llm import ChatGroqWithRetry

SYSTEM_PROMPT = """\
You are an SRE specialist acting as a Code Archaeologist and Git Blame expert.
Your task is to analyze the provided incident report, specifically focusing on the "Recent Deploys" section and any stack traces.

Please provide your diagnosis in the following structure:
1. **Commit Analysis**: Identify which recent commit(s) are most likely related to the failure based on the commit message and stack trace.
2. **Suspect Author**: Note the author of the suspicious commit.
3. **Hypothesis**: The proposed root cause (e.g. Bad Migration, Broken Env, etc.) based on what changed in the recent deploys.
"""


def run_git_blame(incident_context: str) -> str:
    """Run the git-blame subagent to parse recent deploys."""
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
