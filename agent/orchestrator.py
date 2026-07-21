"""
Orchestrator — LangGraph-based SRE incident triage agent.

Uses a custom LangGraph state machine with parallel fan-out to run
three specialized SRE subagents concurrently:
1. log-analyzer: parses traceback and logs
2. deploy-diff: analyzes recent git commits and diffs
3. db-inspector: inspects SQLite database schema and records

Uses Send() to dispatch subagents concurrently. Aggregates results,
reproduces in sandbox via repro-agent, and submits the final diagnosis.
"""
from __future__ import annotations

import json
import logging
import operator
import os
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.constants import Send
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from langgraph.store.base import BaseStore
from agent.docker_sandbox import DockerSandbox
from agent.llm import ChatGroqWithRetry
from agent.memory import save_to_memory, search_memory
from langchain_core.tools import tool


@tool
def submit_diagnosis(
    summary: str,
    root_cause: str,
    evidence: str,
    suggested_fix: str,
    severity: str,
) -> str:
    """Submit the final structured diagnosis for the incident.

    Args:
        summary: One-sentence summary of the failure.
        root_cause: The identified root cause (e.g., N+1 query, null dereference).
        evidence: Key evidence from logs/stack trace supporting the diagnosis.
        suggested_fix: Recommended remediation steps.
        severity: Assessed severity (P1/P2/P3/P4).
    """
    diagnosis = {
        "summary": summary,
        "root_cause": root_cause,
        "evidence": evidence,
        "suggested_fix": suggested_fix,
        "severity": severity,
    }
    return json.dumps(diagnosis, indent=2)

logger = logging.getLogger(__name__)

# Load environment variables from .env
dotenv_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=dotenv_path)


# ── Active Sandbox Registry ────────────────────────────────────────

_active_sandboxes: dict[str, DockerSandbox] = {}


# ── State Definitions ──────────────────────────────────────────────


class AgentState(TypedDict):
    """Parent state for the orchestrator graph."""

    messages: Annotated[list[BaseMessage], add_messages]
    incident_context: str
    sandbox_id: str
    # Reducer to merge subagent outputs from parallel branches
    subagent_outputs: Annotated[list[dict[str, str]], operator.add]
    selected_bug: str
    repro_result: str
    patch_result: str
    diagnosis: str
    phase: str
    # Phase 8: rubric grading
    grader_attempts: int
    grader_feedback: str
    # Phase 7: approval gate
    approval_diff: str
    # Phase 10: time-travel branching
    rejected_hypotheses: Annotated[list[str], operator.add]
    # Phase 15: repo profile metadata
    repo_profile: dict[str, Any]
    # Phase 19: plan-only dry-run mode
    plan_only: bool


class SubagentInput(TypedDict):
    """Input state passed to each parallel subagent branch."""

    incident_context: str
    sandbox_id: str


# ── Node Implementations ───────────────────────────────────────────


def start_sandbox_node(state: AgentState) -> dict:
    """Start the shared sandbox database replica for db-inspector subagent."""
    logger.info("orchestrator: starting shared database sandbox container...")
    sandbox = DockerSandbox(image="python:3.11-slim")
    sandbox.start()

    # Deploy clean build first so database is seeded and ready to inspect
    from agent.sandbox_tools import DeployBreakomaticTool
    deploy_tool = DeployBreakomaticTool(sandbox=sandbox)
    deploy_tool._run(bug_name=None)

    _active_sandboxes[sandbox.id] = sandbox
    logger.info(f"orchestrator: shared sandbox container started: {sandbox.id}")
    return {
        "sandbox_id": sandbox.id,
        "subagent_outputs": [],
        "phase": "check_memory",
    }


def repo_profiler_node(state: AgentState) -> dict:
    """Introspect repository to generate repo profile metadata for downstream agents."""
    logger.info("orchestrator: running repo profiler subagent...")
    from agent.subagents.repo_profiler import profile_repository
    project_root = Path(__file__).parent.parent
    profile = profile_repository(project_root)
    logger.info(f"orchestrator: repository profile generated for service '{profile.service_name}'.")
    return {
        "repo_profile": profile.model_dump(),
    }


def check_memory_node(state: AgentState, store: BaseStore) -> dict:
    """Check if the incident matches a known pattern in memory for the target repository."""
    logger.info("orchestrator: checking memory for known incidents...")
    incident_context = state.get("incident_context", "")
    repo_name = state.get("repo_profile", {}).get("service_name", "breakomatic")
    
    match = search_memory(incident_context, store, repo_name=repo_name)
    if match:
        logger.info(f"orchestrator: Memory hit! Known bug: {match}. Verifying the known fix still applies.")
        print(f"\n🧠  I've seen this, verifying the known fix still applies (Known Bug: {match})\n")
        # Cleanup the shared sandbox since we skip aggregate_node
        sandbox_id = state.get("sandbox_id")
        if sandbox_id:
            sandbox = _active_sandboxes.pop(sandbox_id, None)
            if sandbox is not None:
                try:
                    sandbox.stop()
                    logger.info("orchestrator: shared sandbox stopped early (memory hit).")
                except Exception as e:
                    logger.error(f"orchestrator: failed to clean up shared sandbox: {e}")

        return {
            "selected_bug": match,
            "phase": "reproduce",
        }
    
    logger.info("orchestrator: Memory miss. Proceeding with full investigation.")
    return {"phase": "investigate"}


def log_analyzer_node(state: SubagentInput) -> dict:
    """Run log-analyzer subagent concurrently."""
    logger.info("orchestrator: dispatching log-analyzer subagent...")
    from agent.subagents.log_analyzer import run_log_analyzer

    output = run_log_analyzer(state["incident_context"])
    return {
        "subagent_outputs": [{
            "subagent": "log-analyzer",
            "output": output,
        }]
    }


def deploy_diff_node(state: SubagentInput) -> dict:
    """Run deploy-diff subagent concurrently."""
    logger.info("orchestrator: dispatching deploy-diff subagent...")
    from agent.subagents.deploy_diff import run_deploy_diff

    output = run_deploy_diff(state["incident_context"])
    return {
        "subagent_outputs": [{
            "subagent": "deploy-diff",
            "output": output,
        }]
    }


def db_inspector_node(state: SubagentInput) -> dict:
    """Run db-inspector subagent concurrently against the shared sandbox."""
    logger.info("orchestrator: dispatching db-inspector subagent...")
    from agent.subagents.db_inspector import run_db_inspector

    sandbox = _active_sandboxes.get(state["sandbox_id"])
    if sandbox is None:
        output = "Error: Sandbox not available for database inspection."
    else:
        output = run_db_inspector(state["incident_context"], sandbox)

    return {
        "subagent_outputs": [{
            "subagent": "db-inspector",
            "output": output,
        }]
    }


def apm_analyzer_node(state: SubagentInput) -> dict:
    """Run apm-analyzer subagent concurrently."""
    logger.info("orchestrator: dispatching apm-analyzer subagent...")
    from agent.subagents.apm_analyzer import run_apm_analyzer

    output = run_apm_analyzer(state["incident_context"])
    return {
        "subagent_outputs": [{
            "subagent": "apm-analyzer",
            "output": output,
        }]
    }


def git_blame_node(state: SubagentInput) -> dict:
    """Run git-blame subagent concurrently."""
    logger.info("orchestrator: dispatching git-blame subagent...")
    from agent.subagents.git_blame import run_git_blame

    output = run_git_blame(state["incident_context"])
    return {
        "subagent_outputs": [{
            "subagent": "git-blame",
            "output": output,
        }]
    }


def aggregate_node(state: AgentState) -> dict:
    """Collect subagent findings, stop sandbox, and select best hypothesis."""
    logger.info("orchestrator: aggregating subagent findings...")

    # 1. Always stop the shared sandbox
    sandbox_id = state.get("sandbox_id")
    if sandbox_id:
        sandbox = _active_sandboxes.pop(sandbox_id, None)
        if sandbox is not None:
            try:
                sandbox.stop()
                logger.info("orchestrator: shared sandbox container stopped and removed.")
            except Exception as e:
                logger.error(f"orchestrator: failed to clean up shared sandbox: {e}")

    # 2. Formulate aggregation LLM prompt
    subagent_data = ""
    for out in state.get("subagent_outputs", []):
        subagent_data += f"### Subagent: {out['subagent']}\n{out['output']}\n\n"

    incident_context = state.get("incident_context", "")
    prompt = f"""
You are an SRE Triage lead. Review the incoming incident context and the parallel
investigation outputs.

Incident Context:
{incident_context}

Subagent Outputs:
{subagent_data}

Rejected Hypotheses (DO NOT SELECT THESE):
{state.get("rejected_hypotheses", [])}

Based on this information, pick the MOST LIKELY bug hypothesis from this known list:
- n_plus_one
- null_deref
- bad_migration
- leaked_connection
- broken_env

Provide your final decision as a JSON object:
{{
  "bug_name": "...",
  "justification": "..."
}}
"""

    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    llm = ChatGroqWithRetry(
        model="llama-3.3-70b-versatile",
        api_key=groq_api_key,
        temperature=0.0,
        max_tool_retries=3,
    )

    messages = [
        SystemMessage(content="You are the SRE Orchestrator. Select the correct confirmed bug name."),
        HumanMessage(content=prompt),
    ]

    try:
        response = llm.invoke(messages)
        res_text = response.content.strip()
        if res_text.startswith("```"):
            res_text = "\n".join(
                l for l in res_text.split("\n") if not l.strip().startswith("```")
            )
        selection = json.loads(res_text)
        selected_bug = selection.get("bug_name", "n_plus_one")
        justification = selection.get("justification", "")
    except Exception as e:
        logger.error(f"orchestrator: aggregation decision failed: {e}")
        selected_bug = "n_plus_one"
        justification = f"Fall back to n_plus_one due to aggregation parse error: {e}"

    logger.info(f"orchestrator: selected bug hypothesis: {selected_bug} ({justification})")
    return {
        "selected_bug": selected_bug,
        "phase": "reproduce",
    }


def reproduce_node(state: AgentState) -> dict:
    """Run repro-agent graph (subgraph) to verify the selected hypothesis."""
    selected_bug = state["selected_bug"]
    logger.info(f"orchestrator: invoking repro-agent for bug: {selected_bug}...")

    # Map selected bug to its target endpoint
    endpoint_map = {
        "n_plus_one": {"method": "GET", "path": "/orders"},
        "null_deref": {"method": "GET", "path": "/users/3"},
        "bad_migration": {"method": "GET", "path": "/orders"},
        "leaked_connection": {"method": "GET", "path": "/orders"},
        "broken_env": {"method": "GET", "path": "/health"},
    }
    ep = endpoint_map.get(selected_bug, {"method": "GET", "path": "/orders"})

    from agent.subagents.repro_graph import run_reproduction

    result = run_reproduction(
        hypothesis=f"Suspected {selected_bug} causing system degradation",
        bug_name=selected_bug,
        incident_context=state["incident_context"],
        endpoints_to_test=[ep],
        max_attempts=2,
    )

    logger.info(f"orchestrator: reproduction completed. Verdict: {result['verdict']}")
    return {
        "repro_result": json.dumps(result, indent=2),
        "phase": "patch",
    }


def patch_node(state: AgentState) -> dict:
    """Run the patch writer subagent to fix the bug and create regression tests."""
    selected_bug = state["selected_bug"]
    is_plan_only = state.get("plan_only", False)
    logger.info(f"orchestrator: invoking patch-writer for bug: {selected_bug} (plan_only={is_plan_only})...")

    from agent.audit import AuditLogger
    audit_logger = AuditLogger.get_instance()

    if is_plan_only:
        audit_logger.log_event(
            tool_name="patch_writer",
            caller_node="patch_node",
            target_system="sandbox",
            input_summary=f"Plan-only dry-run for bug {selected_bug}. Skipped file modification.",
            status="DRY_RUN",
        )
        patch_output = f"[PLAN-ONLY DRY RUN] Proposed investigation plan & fix generated for hypothesis '{selected_bug}'. No system files modified."
    else:
        from agent.subagents.patch_writer import run_patch_writer
        patch_output = run_patch_writer(selected_bug)
        audit_logger.log_event(
            tool_name="patch_writer",
            caller_node="patch_node",
            target_system="sandbox",
            input_summary=f"Applied patch fix for bug {selected_bug}.",
            status="SUCCESS",
        )

    logger.info(f"orchestrator: patch-writer completed. Output preview: {patch_output[:300]}")
    return {
        "patch_result": patch_output,
        "phase": "grade",
    }


def grader_node(state: AgentState) -> dict:
    """Grade the patch against rubric criteria. Reject band-aid fixes."""
    selected_bug = state["selected_bug"]
    grader_attempts = state.get("grader_attempts", 0)
    logger.info(f"orchestrator: grading patch for bug: {selected_bug} (attempt {grader_attempts + 1})...")

    from agent.rubric_config import grade_patch

    result = grade_patch(
        bug_name=selected_bug,
        repro_result=state.get("repro_result", ""),
        incident_context=state.get("incident_context", ""),
        skip_rerun=False,  # Run the rerun verification to satisfy Phase 8
    )

    logger.info(f"orchestrator: rubric grade: {'PASS' if result.passed else 'FAIL'} ({result.score:.0%})")
    return {
        "grader_attempts": grader_attempts + 1,
        "grader_feedback": result.summary(),
        "phase": "approve" if result.passed else "revise",
    }


def approval_gate_node(state: AgentState) -> dict:
    """Surface the patch diff for human review. This node is interrupted before execution."""
    selected_bug = state["selected_bug"]
    logger.info(f"orchestrator: surfacing diff for approval gate (bug: {selected_bug})...")

    from agent.approval import get_patch_diff
    diff = get_patch_diff(selected_bug)

    grader_feedback = state.get("grader_feedback", "")
    approval_info = (
        f"=== RUBRIC GRADE ===\n{grader_feedback}\n\n"
        f"=== PROPOSED PATCH DIFF ===\n{diff}\n"
    )

    logger.info(f"orchestrator: approval gate ready. Diff length: {len(diff)} chars")
    return {
        "approval_diff": approval_info,
        "phase": "approve",
    }


def diagnose_node(state: AgentState, store: BaseStore) -> dict:
    """Generate and submit the final structured diagnosis using the LLM."""
    logger.info("orchestrator: generating final structured diagnosis...")

    subagent_data = ""
    for out in state.get("subagent_outputs", []):
        subagent_data += f"### Subagent: {out['subagent']}\n{out['output']}\n\n"

    prompt = (
        f"We have finalized our SRE incident triage process:\n\n"
        f"**Subagent Findings**:\n{subagent_data}\n"
        f"**Reproduction Verification**:\n{state['repro_result']}\n\n"
        f"**Patch Writer Fix & Test Output**:\n{state.get('patch_result', 'N/A')}\n\n"
        f"Original Incident Context:\n{state['incident_context']}\n\n"
        "Please provide the final structured diagnosis as a raw JSON block (do not wrap in markdown code fence) containing the following fields:\n"
        "{\n"
        "  \"summary\": \"A high-level summary of the incident and what was observed\",\n"
        "  \"root_cause\": \"The identified root cause of the incident\",\n"
        "  \"evidence\": \"The key evidence from logs, traces, or reproduction\",\n"
        "  \"suggested_fix\": \"The suggested code/config fix\",\n"
        "  \"severity\": \"P0, P1, P2, or P3\"\n"
        "}\n"
    )

    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    llm = ChatGroqWithRetry(
        model="llama-3.3-70b-versatile",
        api_key=groq_api_key,
        temperature=0.0,
        max_tool_retries=3,
    )

    messages = [
        SystemMessage(content="You are the SRE Orchestrator. Output ONLY raw JSON matching the requested schema. No conversational filler."),
        HumanMessage(content=prompt),
    ]

    try:
        response = llm.invoke(messages)
        content = response.content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        parsed = json.loads(content)
        # Ensure all required keys are present
        for key in ["summary", "root_cause", "evidence", "suggested_fix", "severity"]:
            if key not in parsed:
                parsed[key] = "N/A"
        diagnosis_data = json.dumps(parsed, indent=2)
    except Exception as e:
        logger.warning(f"orchestrator: failed to parse JSON from LLM: {e}. Falling back...")
        diagnosis_data = json.dumps({
            "summary": "Triage analysis completed.",
            "root_cause": state.get("selected_bug", "N/A"),
            "evidence": "Verification: " + state.get("repro_result", "N/A"),
            "suggested_fix": "Please check database and commit history.",
            "severity": "P1",
        }, indent=2)

    bug_name = state.get("selected_bug", "unknown")
    repo_name = state.get("repo_profile", {}).get("service_name", "breakomatic")
    if bug_name != "unknown":
        try:
            save_to_memory(bug_name, diagnosis_data, store, repo_name=repo_name)
        except Exception as e:
            logger.error(f"orchestrator: failed to save to memory: {e}")

    return {
        "diagnosis": diagnosis_data,
        "phase": "done",
    }



# ── Routing Logic ──────────────────────────────────────────────────


def route_to_subagents(state: AgentState) -> list[Send]:
    """Dynamically fan out and dispatch five specialized subagents in parallel."""
    return [
        Send("log_analyzer", {
            "incident_context": state["incident_context"],
            "sandbox_id": state["sandbox_id"],
        }),
        Send("deploy_diff", {
            "incident_context": state["incident_context"],
            "sandbox_id": state["sandbox_id"],
        }),
        Send("db_inspector", {
            "incident_context": state["incident_context"],
            "sandbox_id": state["sandbox_id"],
        }),
        Send("apm_analyzer", {
            "incident_context": state["incident_context"],
            "sandbox_id": state["sandbox_id"],
        }),
        Send("git_blame", {
            "incident_context": state["incident_context"],
            "sandbox_id": state["sandbox_id"],
        }),
    ]


# ── Graph Builder ──────────────────────────────────────────────────


def build_orchestrator(
    model_name: str = "llama-3.3-70b-versatile",
    sandbox: Any = None,
    debug: bool = False,
):
    """Build SRE orchestrator with Send-based parallel fan-out."""
    graph = StateGraph(AgentState)

    # Add Nodes
    graph.add_node("start_sandbox", start_sandbox_node)
    graph.add_node("repo_profiler", repo_profiler_node)
    graph.add_node("check_memory", check_memory_node)
    graph.add_node("log_analyzer", log_analyzer_node)
    graph.add_node("deploy_diff", deploy_diff_node)
    graph.add_node("db_inspector", db_inspector_node)
    graph.add_node("apm_analyzer", apm_analyzer_node)
    graph.add_node("git_blame", git_blame_node)
    graph.add_node("aggregate", aggregate_node)
    graph.add_node("reproduce", reproduce_node)
    graph.add_node("patch", patch_node)
    graph.add_node("grader", grader_node)
    graph.add_node("approval_gate", approval_gate_node)
    graph.add_node("diagnose", diagnose_node)

    # Set Entry Point
    graph.set_entry_point("start_sandbox")

    # Flow: start_sandbox -> repo_profiler -> check_memory -> fan-out OR reproduce
    graph.add_edge("start_sandbox", "repo_profiler")
    graph.add_edge("repo_profiler", "check_memory")

    def route_after_memory(state: AgentState):
        if state.get("phase") == "reproduce":
            return "reproduce"
        return route_to_subagents(state)

    graph.add_conditional_edges("check_memory", route_after_memory, ["log_analyzer", "deploy_diff", "db_inspector", "apm_analyzer", "git_blame", "reproduce"])

    # Gather: each subagent node flows directly into the aggregate node
    graph.add_edge("log_analyzer", "aggregate")
    graph.add_edge("deploy_diff", "aggregate")
    graph.add_edge("db_inspector", "aggregate")
    graph.add_edge("apm_analyzer", "aggregate")
    graph.add_edge("git_blame", "aggregate")

    # Linear flow for resolution
    graph.add_edge("aggregate", "reproduce")
    graph.add_edge("reproduce", "patch")
    graph.add_edge("patch", "grader")

    # Grader: pass -> approval_gate, fail -> patch (retry, max 2)
    def route_after_grader(state: AgentState) -> str:
        """Route based on grader result: pass to approval, fail back to patch."""
        grader_attempts = state.get("grader_attempts", 0)
        phase = state.get("phase", "")
        if phase == "revise" and grader_attempts < 2:
            logger.info(f"orchestrator: grader rejected patch (attempt {grader_attempts}). Sending back to patch_writer...")
            return "patch"
        return "approval_gate"

    graph.add_conditional_edges(
        "grader",
        route_after_grader,
        {"patch": "patch", "approval_gate": "approval_gate"},
    )

    graph.add_edge("approval_gate", "diagnose")
    graph.add_edge("diagnose", END)

    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.store.sqlite import SqliteStore

    conn = sqlite3.connect("checkpoints.db", check_same_thread=False)
    memory = SqliteSaver(conn)
    
    store_conn = sqlite3.connect("store.db", check_same_thread=False, isolation_level=None)
    store = SqliteStore(store_conn)
    store.setup()

    # Interrupt before approval_gate: human reviews diff + rubric grade
    compiled = graph.compile(checkpointer=memory, store=store, interrupt_before=["approval_gate"], interrupt_after=["reproduce"])
    return compiled


def create_orchestrator(
    model_name: str = "llama-3.3-70b-versatile",
    backend: Any = None,
    debug: bool = False,
):
    """Convenience wrapper matching previous API signature."""
    return build_orchestrator(
        model_name=model_name,
        sandbox=backend,
        debug=debug,
    )
