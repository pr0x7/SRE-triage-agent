"""
DB Inspector subagent implementation.
Queries database tables, schemas, and checks database state inside the sandbox.
"""
from __future__ import annotations

import os
from typing import Any
from langchain_core.messages import SystemMessage, HumanMessage
from agent.llm import ChatGroqWithRetry
from agent.sandbox_tools import DbQueryTool
from agent.docker_sandbox import DockerSandbox

SYSTEM_PROMPT = """\
You are the DB Inspector SRE subagent.
Your goal is to inspect the database schema and table records inside the sandbox database \
to diagnose if schema issues or database state are causing the incident.

You have access to:
1. db_query: run SELECT queries. Remember only read-only SELECT queries are allowed.

Check table schemas (e.g. using sqlite_master or PRAGMA table_info) or table records, and report your findings.
Provide a clear analysis summarizing:
1. Database tables and schemas inspected.
2. Data or schema issues found.
3. How they relate to the incident traceback or error.
"""


def run_db_inspector(incident_context: str, sandbox: DockerSandbox) -> str:
    """Run the db-inspector subagent to inspect database state."""
    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    llm = ChatGroqWithRetry(
        model="llama-3.3-70b-versatile",
        api_key=groq_api_key,
        temperature=0.0,
        max_tool_retries=3,
    )

    db_query_tool = DbQueryTool(sandbox=sandbox)
    tools = [db_query_tool]
    
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Incident Context:\n{incident_context}\n\nPlease inspect the database state."),
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
