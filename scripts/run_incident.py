#!/usr/bin/env python3
"""
CLI entrypoint to run an incident triage process using the orchestrator agent.

Usage:
    python scripts/run_incident.py --incident incidents/sample_n_plus_one.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.orchestrator import create_orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run SRE Orchestrator Agent on an incident payload."
    )
    parser.add_argument(
        "--incident",
        type=str,
        required=True,
        help="Path to the incident JSON payload file",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logs",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="llama-3.3-70b-versatile",
        help="Groq model name to use (default: llama-3.3-70b-versatile)",
    )
    args = parser.parse_args()

    # Resolve file path
    file_path = Path(args.incident)
    if not file_path.exists():
        print(f"❌  Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with file_path.open() as f:
            incident_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌  Error: Invalid JSON file {file_path}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"📋  Loaded Incident: {incident_data.get('incident_id', 'Unknown')}")
    print(f"    Title: {incident_data.get('title', 'No Title')}")
    print(f"    Service: {incident_data.get('service', 'No Service')}")
    print("─" * 60)

    # Construct incident context prompt
    prompt = (
        f"Incident details:\n"
        f"Title: {incident_data.get('title')}\n"
        f"Severity: {incident_data.get('severity')}\n"
        f"Timestamp: {incident_data.get('timestamp')}\n\n"
        f"Stack Trace:\n```\n{incident_data.get('stack_trace')}\n```\n\n"
        f"Logs:\n" + "\n".join(incident_data.get("logs", [])) + "\n\n"
        f"Recent Deploys:\n" + json.dumps(incident_data.get("recent_deploys", []), indent=2) + "\n\n"
        f"Metrics:\n" + json.dumps(incident_data.get("metrics", {}), indent=2)
    )

    print("🤖  Initializing SRE Orchestrator Agent...")
    try:
        agent = create_orchestrator(model_name=args.model, debug=args.debug)
    except Exception as e:
        print(f"❌  Initialization failed: {e}", file=sys.stderr)
        sys.exit(1)

    print("🚀  Invoking agent...")
    try:
        config = {"configurable": {"thread_id": incident_data.get("incident_id", "default_thread")}}
        
        # Initial input state (only passed on first invoke)
        input_state = {
            "messages": [],
            "incident_context": prompt,
            "sandbox_id": "",
            "subagent_outputs": [],
            "selected_bug": "",
            "repro_result": "",
            "patch_result": "",
            "diagnosis": "",
            "phase": "start",
            "grader_attempts": 0,
            "grader_feedback": "",
            "approval_diff": "",
            "rejected_hypotheses": [],
        }

        first_run = True
        
        while True:
            state = agent.get_state(config)
            
            # If graph finished, break
            if not state.next and not first_run:
                break
                
            if state.next:
                next_node = state.next[0]
                
                # Phase 7: Approval Gate Interruption
                if next_node == "approval_gate":
                    from agent.approval import prompt_approval_gate
                    selected_bug = state.values.get("selected_bug")
                    grader_feedback = state.values.get("grader_feedback", "")
                    approved = prompt_approval_gate(selected_bug, grader_feedback)
                    if not approved:
                        print("❌ Execution aborted. Patch rejected.")
                        sys.exit(1)
                    print("🚀 Resuming execution...")
                    agent.invoke(None, config=config)
                    continue

                # Phase 10: Time-travel Branching Interruption
                if next_node == "patch":
                    # Reproduce finished. Check the verdict.
                    repro_res_str = state.values.get("repro_result", "{}")
                    verdict = ""
                    try:
                        verdict = json.loads(repro_res_str).get("verdict", "")
                    except Exception:
                        pass
                    
                    if verdict and verdict != "confirmed":
                        selected_bug = state.values.get("selected_bug")
                        print(f"\n🌲 Branching: Hypothesis '{selected_bug}' rejected. (Verdict: {verdict})")
                        
                        history = list(agent.get_state_history(config))
                        target_state = next((h for h in history if h.next == ("aggregate",)), None)
                        
                        if target_state:
                            print("⏪ Rewinding checkpoint to right after triage to try the next hypothesis...")
                            config = agent.update_state(
                                target_state.config,
                                {"rejected_hypotheses": [selected_bug]}
                            )
                            continue
                        else:
                            print("⚠️ Warning: Cannot rewind (no aggregate node found in history). Proceeding anyway...")
                            
            # Invoke the graph
            if first_run and not state.next:
                agent.invoke(input_state, config=config)
                first_run = False
            else:
                agent.invoke(None, config=config)

        # Retrieve the final response state
        response = agent.get_state(config).values

        print("\n" + "═" * 60)
        print("🏁  Agent Run Completed")
        print("═" * 60)

        # Print selected bug and reproduction details
        print(f"\nHypothesis Selected: {response.get('selected_bug')}")
        print("\n🔍  Reproduction Result:")
        print(response.get("repro_result"))

        # Print patch writer result
        print("\n🛠️  Patch Writer Result:")
        print(response.get("patch_result"))

        # Print structured diagnosis
        diagnosis = response.get("diagnosis", "")
        if diagnosis:
            print("\n📊  Structured Diagnosis:")
            print(diagnosis)
        else:
            print("\nNo diagnosis returned.")

    except Exception as e:
        print(f"\n❌  Run failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
