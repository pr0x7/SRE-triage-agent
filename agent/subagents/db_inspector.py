"""
DB Inspector subagent implementation.
Queries database tables, schemas, and checks database state inside the sandbox or reflected databases.
"""
from __future__ import annotations

import os
from typing import Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from agent.llm import ChatGroqWithRetry
from agent.sandbox_tools import DbQueryTool
from agent.docker_sandbox import DockerSandbox
from agent.db_adapter import DatabaseInspector

SYSTEM_PROMPT = """\
You are the DB Inspector SRE subagent.
Your goal is to inspect reflected database schemas and table records \
to diagnose if schema issues, missing columns, or database state are causing the incident.

You have access to:
1. db_query: run SELECT queries. Only read-only SELECT queries are enforced at connection-level.

Review the reflected database schema provided and check table records, reporting your findings:
1. Database tables and schemas inspected.
2. Data or schema issues found (e.g. missing column, unindexed foreign key, exhausted connection pool).
3. How they relate to the incident traceback or error.
"""


def run_db_inspector(
    incident_context: str,
    sandbox: Optional[DockerSandbox] = None,
    db_inspector: Optional[DatabaseInspector] = None,
) -> str:
    """Run the db-inspector subagent to inspect database state and reflected schemas.

    Args:
        incident_context: Incident log/traceback details.
        sandbox: Optional active Docker sandbox for execution.
        db_inspector: Optional DatabaseInspector for schema reflection and read-only query execution.
    """
    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    llm = ChatGroqWithRetry(
        model="llama-3.3-70b-versatile",
        api_key=groq_api_key,
        temperature=0.0,
        max_tool_retries=3,
    )

    schema_summary = ""
    if db_inspector:
        try:
            schema_summary = db_inspector.format_schema_summary()
        except Exception as e:
            schema_summary = f"Failed to reflect schema: {e}"

    tools = []
    if sandbox:
        db_query_tool = DbQueryTool(sandbox=sandbox)
        tools.append(db_query_tool)

    llm_with_tools = llm.bind_tools(tools) if tools else llm
    tool_map = {t.name: t for t in tools}

    prompt_content = f"Incident Context:\n{incident_context}\n\n"
    if schema_summary:
        prompt_content += f"{schema_summary}\n\n"
    prompt_content += "Please inspect the database state and analyze if schema or table records cause the failure."

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=prompt_content),
    ]

    if not tools:
        response = llm.invoke(messages)
        return response.content

    # ReAct-style loop for up to 3 turns
    for _ in range(3):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not getattr(response, "tool_calls", None):
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
