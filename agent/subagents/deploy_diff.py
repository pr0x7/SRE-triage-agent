"""
Deploy Diff subagent implementation.
Analyzes recent deployment diffs and git history to correlate changes with the incident.
"""
from __future__ import annotations

import os
from typing import Any
from langchain_core.messages import SystemMessage, HumanMessage
from agent.llm import ChatGroqWithRetry
from agent.sandbox_tools import GitLogTool, GitDiffTool

SYSTEM_PROMPT = """\
You are the Deploy Diff SRE subagent.
Your goal is to inspect the git commit history and specific commit diffs to find code changes \
that correlate with the production incident.

You have access to:
1. git_log: retrieve recent commits.
2. git_diff: show what changes were made in a commit.

Examine the git log, diff relevant commits (especially those mentioned in the incident as recent deploys), \
and report your findings.
Provide a clear analysis summarizing:
1. Commits inspected.
2. Code changes found that are suspicious.
3. How they relate to the traceback or error logs.
"""


def run_deploy_diff(incident_context: str) -> str:
    """Run the deploy-diff subagent to analyze git changes."""
    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    llm = ChatGroqWithRetry(
        model="llama-3.3-70b-versatile",
        api_key=groq_api_key,
        temperature=0.0,
        max_tool_retries=3,
    )

    git_log_tool = GitLogTool()
    git_diff_tool = GitDiffTool()
    tools = [git_log_tool, git_diff_tool]
    
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Incident Context:\n{incident_context}\n\nPlease investigate recent commits."),
    ]

    # ReAct-style loop for up to 3 turns
    for _ in range(3):
        response = llm_with_tools.invoke(messages)
        messages.append(response)
        
        if not response.tool_calls:
            break
            
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            if tool_name in tool_map:
                try:
                    result = tool_map[tool_name].invoke(tool_args)
                except Exception as e:
                    result = f"Tool error: {e}"
            else:
                result = f"Unknown tool: {tool_name}"
            messages.append(HumanMessage(content=f"Tool output ({tool_name}):\n{result}"))

    return messages[-1].content
