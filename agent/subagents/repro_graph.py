"""
Repro Graph — custom LangGraph StateGraph for incident reproduction.

NOT a ReAct loop — a real state machine:
  provision → deploy_and_replay → observe → decide → cleanup

The repro-agent, given a hypothesis from the orchestrator:
  1. Provisions a fresh Docker sandbox container
  2. Deploys break-o-matic with the suspected bug injected
  3. Replays the failing request pattern to reproduce the issue
  4. Observes the result (status codes, latency, error messages, logs)
  5. Decides: confirmed / retry with adjusted params / escalate
  6. Always cleans up the sandbox (reachable from every branch)

The graph guarantees sandbox cleanup via a dedicated cleanup node that is
reachable from every terminal state — no leaked containers.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from agent.docker_sandbox import DockerSandbox
from agent.llm import ChatGroqWithRetry
from agent.sandbox_tools import DeployBreakomaticTool, QueryBreakomaticTool

logger = logging.getLogger(__name__)


# ── State ─────────────────────────────────────────────────────────


class ReproState(TypedDict):
    """State for the reproduction subgraph."""

    # Input from orchestrator
    hypothesis: str          # e.g. "n_plus_one", "leaked_connection", "null_deref"
    bug_name: str            # The breakomatic bug module to inject
    endpoints_to_test: list[dict]  # [{"method": "GET", "path": "/orders"}, ...]
    incident_context: str    # Original incident description for LLM context

    # Internal state
    messages: Annotated[list[BaseMessage], add_messages]
    sandbox_id: str          # Container ID for tracking
    deploy_result: str       # Result of deploy step
    observations: list[dict] # Collected HTTP responses & logs
    attempt: int             # Current attempt number (0-indexed)
    max_attempts: int        # Max retries before escalation

    # Output
    verdict: str             # "confirmed" | "not_reproduced" | "escalate"
    evidence: str            # Structured evidence from reproduction
    sandbox_cleaned: bool    # True once cleanup is done


# ── Shared sandbox reference (set by the graph builder) ───────────

_sandbox_ref: dict[str, DockerSandbox | None] = {"sandbox": None}


# ── Graph Nodes ───────────────────────────────────────────────────


def provision_node(state: ReproState) -> dict:
    """Provision a fresh Docker sandbox container."""
    logger.info("repro-agent: provisioning sandbox...")

    sandbox = DockerSandbox(image="python:3.11-slim")
    sandbox.start()

    # Store in shared ref for other nodes
    _sandbox_ref["sandbox"] = sandbox

    logger.info(f"repro-agent: sandbox started: {sandbox.id}")
    return {
        "sandbox_id": sandbox.id,
        "attempt": 0,
        "observations": [],
        "messages": [
            SystemMessage(content=(
                "You are the SRE reproduction agent. Your job is to analyze "
                "reproduction attempt results and determine if the hypothesized "
                "bug has been confirmed."
            )),
        ],
    }


def deploy_and_replay_node(state: ReproState) -> dict:
    """Deploy break-o-matic with the bug injected and replay failing requests."""
    sandbox = _sandbox_ref["sandbox"]
    if sandbox is None:
        return {
            "verdict": "escalate",
            "evidence": "Sandbox not available — cannot reproduce.",
        }

    bug_name = state["bug_name"]
    attempt = state.get("attempt", 0)
    logger.info(f"repro-agent: deploy attempt {attempt + 1}, bug={bug_name}")

    # Deploy with the suspected bug
    deploy_tool = DeployBreakomaticTool(sandbox=sandbox)
    deploy_result = deploy_tool._run(bug_name=bug_name)

    # Replay the failing endpoints
    query_tool = QueryBreakomaticTool(sandbox=sandbox)
    observations: list[dict] = []

    endpoints = state.get("endpoints_to_test", [{"method": "GET", "path": "/orders"}])

    # If the bug is leaked_connection, we need to query multiple times to exhaust the connection pool
    if bug_name == "leaked_connection":
        # Loop 10 times to exhaust pool size of 5 + max_overflow of 3 = 8
        logger.info("repro-agent: Leaked connection bug suspected. Running 10 requests to trigger exhaustion.")
        endpoints_to_run = endpoints * 10
    else:
        endpoints_to_run = endpoints

    for i, endpoint in enumerate(endpoints_to_run):
        method = endpoint.get("method", "GET")
        path = endpoint.get("path", "/orders")
        payload = endpoint.get("payload")

        start_time = time.time()
        try:
            result_str = query_tool._run(method=method, path=path, payload=payload)
            elapsed_ms = (time.time() - start_time) * 1000

            try:
                result = json.loads(result_str)
            except json.JSONDecodeError:
                result = {"raw": result_str}

            observations.append({
                "request_num": i + 1,
                "endpoint": f"{method} {path}",
                "status": result.get("status", "unknown"),
                "response_preview": str(result.get("body", ""))[:500],
                "error": result.get("error"),
                "latency_ms": round(elapsed_ms, 1),
                "attempt": attempt + 1,
            })
        except Exception as e:
            observations.append({
                "request_num": i + 1,
                "endpoint": f"{method} {path}",
                "status": "error",
                "error": str(e),
                "attempt": attempt + 1,
            })

    # Also grab server logs for evidence
    try:
        log_result = sandbox.execute("cat /tmp/breakomatic.log 2>/dev/null | tail -100")
        server_logs = log_result.output.strip()
    except Exception:
        server_logs = "(logs unavailable)"

    if server_logs:
        observations.append({
            "type": "server_logs",
            "content": server_logs[:3000],
            "attempt": attempt + 1,
        })

    return {
        "deploy_result": deploy_result,
        "observations": state.get("observations", []) + observations,
        "attempt": attempt + 1,
    }


def observe_node(state: ReproState) -> dict:
    """Use the LLM to analyze the reproduction observations."""
    sandbox = _sandbox_ref["sandbox"]
    observations = state.get("observations", [])
    hypothesis = state["hypothesis"]
    attempt = state.get("attempt", 1)
    incident_context = state.get("incident_context", "")

    # Build the analysis prompt with explicit criteria for each bug type
    obs_text = json.dumps(observations, indent=2)
    prompt = (
        f"## Reproduction Attempt #{attempt}\n\n"
        f"**Hypothesis**: {hypothesis}\n"
        f"**Bug injected**: {state['bug_name']}\n\n"
        f"**Original Incident Context**:\n{incident_context}\n\n"
        f"**Observations from replay**:\n```json\n{obs_text}\n```\n\n"
        f"**Deploy Result**: {state.get('deploy_result', 'N/A')}\n\n"
        "Analyze these results to determine if the hypothesized bug has been successfully reproduced.\n"
        "Here are the success criteria for each bug type:\n"
        "1. **n_plus_one**:\n"
        "   - Confirmation: The endpoint works (returns 200 OK), but the server_logs show a separate SELECT query "
        "     for items for multiple different order IDs (e.g. 'SELECT * FROM items WHERE order_id = 1', "
        "     'SELECT * FROM items WHERE order_id = 2', etc.). If the logs show 'Bug injected: n_plus_one' and multiple "
        "     item queries, this is CONFIRMED (reproduced = true, recommendation = 'confirmed').\n"
        "2. **null_deref**:\n"
        "   - Confirmation: Querying the endpoint (specifically /users/3 or /users/5) returns a 500 error, "
        "     and the logs show an 'AttributeError: 'NoneType' object has no attribute 'upper''.\n"
        "3. **bad_migration**:\n"
        "   - Confirmation: Querying an orders-related endpoint returns a 500 error, "
        "     and the logs show 'sqlalchemy.exc.OperationalError: no such column: orders.status'.\n"
        "4. **leaked_connection**:\n"
        "   - Confirmation: The first 8 requests succeed (status 200), but subsequent requests (9th, 10th) hang and "
        "     fail with a 500 error or sqlalchemy.exc.TimeoutError indicating connection pool exhaustion.\n"
        "5. **broken_env**:\n"
        "   - Confirmation: The service fails to start entirely (deploy_result indicates failure, "
        "     or uvicorn output is empty / shows traceback on startup).\n\n"
        "Determine if the observations meet the confirmation criteria for the injected bug.\n"
        "If you recommend a retry (because you suspect a specific endpoint shape, parameters, or "
        "additional headers are needed), you can optionally include an 'adjusted_parameters' key "
        "containing: {'endpoints_to_test': [{'method': 'GET', 'path': '/users/3'}]}.\n\n"
        "Respond with a JSON object ONLY, with no extra text or markdown code fences:\n"
        '{"reproduced": true/false, "confidence": "high"/"medium"/"low", '
        '"evidence_summary": "...", "recommendation": "confirmed"/"retry"/"escalate", '
        '"adjusted_parameters": null or {"endpoints_to_test": [{"method": "...", "path": "..."}]}}'
    )

    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    llm = ChatGroqWithRetry(
        model="llama-3.3-70b-versatile",
        api_key=groq_api_key,
        temperature=0.0,
        max_tool_retries=3,
    )

    messages = [
        SystemMessage(content=(
            "You are the SRE reproduction analyst. Analyze reproduction attempt "
            "results and determine if the bug was reproduced. Always respond with "
            "valid JSON only, no markdown fences or pre-text/post-text."
        )),
        HumanMessage(content=prompt),
    ]

    try:
        response = llm.invoke(messages)
        analysis_text = response.content.strip()

        # Try to parse the JSON response
        # Strip markdown fences if present
        if analysis_text.startswith("```"):
            lines = analysis_text.split("\n")
            analysis_text = "\n".join(
                l for l in lines if not l.strip().startswith("```")
            )

        try:
            analysis = json.loads(analysis_text)
        except json.JSONDecodeError:
            analysis = {
                "reproduced": False,
                "confidence": "low",
                "evidence_summary": analysis_text[:500],
                "recommendation": "retry" if attempt < state.get("max_attempts", 2) else "escalate",
                "adjusted_parameters": None,
            }
    except Exception as e:
        logger.error(f"repro-agent: LLM analysis failed: {e}")
        analysis = {
            "reproduced": False,
            "confidence": "low",
            "evidence_summary": f"LLM analysis failed: {e}",
            "recommendation": "escalate",
            "adjusted_parameters": None,
        }

    return {
        "messages": [
            HumanMessage(content=prompt),
            AIMessage(content=json.dumps(analysis, indent=2)),
        ],
        "evidence": json.dumps(analysis, indent=2),
    }


def decide_node(state: ReproState) -> dict:
    """Decide verdict based on the LLM analysis and apply adjusted parameters on retry."""
    evidence_str = state.get("evidence", "{}")
    attempt = state.get("attempt", 1)
    max_attempts = state.get("max_attempts", 2)

    try:
        analysis = json.loads(evidence_str)
    except json.JSONDecodeError:
        analysis = {"recommendation": "escalate"}

    recommendation = analysis.get("recommendation", "escalate")
    adjusted_params = analysis.get("adjusted_parameters")

    if recommendation == "confirmed":
        return {"verdict": "confirmed"}
    elif recommendation == "retry" and attempt < max_attempts:
        update = {"verdict": "retry"}
        # Apply adjusted parameters if provided by the LLM
        if adjusted_params and isinstance(adjusted_params, dict):
            if "endpoints_to_test" in adjusted_params:
                logger.info(f"repro-agent: Adjusting endpoints_to_test to: {adjusted_params['endpoints_to_test']}")
                update["endpoints_to_test"] = adjusted_params["endpoints_to_test"]
        return update
    else:
        # Either explicit escalation or max retries exceeded
        verdict = "not_reproduced" if recommendation != "escalate" else "escalate"
        return {"verdict": verdict}


def cleanup_node(state: ReproState) -> dict:
    """Always clean up the sandbox — reachable from every terminal path."""
    sandbox = _sandbox_ref["sandbox"]
    if sandbox is not None:
        try:
            sandbox.stop()
            logger.info(f"repro-agent: sandbox {state.get('sandbox_id', '?')} cleaned up")
        except Exception as e:
            logger.error(f"repro-agent: cleanup failed: {e}")
        finally:
            _sandbox_ref["sandbox"] = None

    return {"sandbox_cleaned": True}


# ── Edge Logic ────────────────────────────────────────────────────


def after_decide(state: ReproState) -> Literal["deploy_and_replay", "cleanup"]:
    """After decide: retry (loop back) or proceed to cleanup."""
    if state.get("verdict") == "retry":
        return "deploy_and_replay"
    return "cleanup"


# ── Graph Builder ─────────────────────────────────────────────────


def build_repro_graph() -> Any:
    """Build the reproduction subgraph as a LangGraph StateGraph.

    Flow:
        provision → deploy_and_replay → observe → decide → cleanup
                         ↑                          │
                         └──── retry ───────────────┘

    The cleanup node is reachable from every terminal state.
    """
    graph = StateGraph(ReproState)

    # Add nodes
    graph.add_node("provision", provision_node)
    graph.add_node("deploy_and_replay", deploy_and_replay_node)
    graph.add_node("observe", observe_node)
    graph.add_node("decide", decide_node)
    graph.add_node("cleanup", cleanup_node)

    # Set entry point
    graph.set_entry_point("provision")

    # Linear edges
    graph.add_edge("provision", "deploy_and_replay")
    graph.add_edge("deploy_and_replay", "observe")
    graph.add_edge("observe", "decide")

    # Conditional: decide → retry (deploy_and_replay) or cleanup
    graph.add_conditional_edges(
        "decide",
        after_decide,
        {"deploy_and_replay": "deploy_and_replay", "cleanup": "cleanup"},
    )

    # Cleanup always ends
    graph.add_edge("cleanup", END)

    return graph.compile()


# ── Convenience runner ────────────────────────────────────────────


def run_reproduction(
    hypothesis: str,
    bug_name: str,
    incident_context: str = "",
    endpoints_to_test: list[dict] | None = None,
    max_attempts: int = 2,
) -> dict:
    """Run the reproduction subgraph and return the result.

    This is the main entry point for the orchestrator to call.
    Always cleans up the sandbox, even on exception.

    Returns:
        dict with keys: verdict, evidence, observations, sandbox_cleaned
    """
    if endpoints_to_test is None:
        endpoints_to_test = [{"method": "GET", "path": "/orders"}]

    graph = build_repro_graph()

    initial_state: ReproState = {
        "hypothesis": hypothesis,
        "bug_name": bug_name,
        "endpoints_to_test": endpoints_to_test,
        "incident_context": incident_context,
        "messages": [],
        "sandbox_id": "",
        "deploy_result": "",
        "observations": [],
        "attempt": 0,
        "max_attempts": max_attempts,
        "verdict": "",
        "evidence": "",
        "sandbox_cleaned": False,
    }

    try:
        result = graph.invoke(initial_state)
        return {
            "verdict": result.get("verdict", "escalate"),
            "evidence": result.get("evidence", ""),
            "observations": result.get("observations", []),
            "sandbox_cleaned": result.get("sandbox_cleaned", False),
        }
    except Exception as e:
        logger.error(f"repro-agent: graph execution failed: {e}")
        # ALWAYS clean up on exception
        cleanup_node({"sandbox_id": initial_state.get("sandbox_id", "")})
        return {
            "verdict": "escalate",
            "evidence": json.dumps({"error": str(e)}),
            "observations": [],
            "sandbox_cleaned": True,
        }
