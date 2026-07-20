"""
Evaluation harness — orchestrates end-to-end runs and collects results.
"""
from __future__ import annotations

import os
import sys
import json
import sqlite3
import shutil
import time
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from agent.orchestrator import create_orchestrator
from breakomatic.alerts import generate_alert
from breakomatic.config import clear_active_bug, set_active_bug

BUGS = ["n_plus_one", "null_deref", "bad_migration", "leaked_connection", "broken_env"]

class EvalHarness:
    def __init__(self):
        self.original_contents: dict[str, str] = {}
        self.backup_original_files()

    def backup_original_files(self):
        """Backup all original buggy code files in memory."""
        for bug in BUGS:
            path = PROJECT_ROOT / "breakomatic" / "bugs" / f"{bug}.py"
            if path.exists():
                self.original_contents[bug] = path.read_text()
            else:
                self.original_contents[bug] = ""

    def restore_all_files(self):
        """Restore all bug files and delete any temporary .orig or db files."""
        print("\n🧹 Cleaning up and restoring codebase to original buggy state...")
        for bug in BUGS:
            path = PROJECT_ROOT / "breakomatic" / "bugs" / f"{bug}.py"
            orig_path = path.with_suffix(".py.orig")
            if bug in self.original_contents and self.original_contents[bug]:
                path.write_text(self.original_contents[bug])
            if orig_path.exists():
                orig_path.unlink()
        
        # Remove any regression test file generated during the evaluation
        reg_test = PROJECT_ROOT / "evals" / "test_regression.py"
        if reg_test.exists():
            reg_test.unlink()

        # Remove database files
        db_files = [
            "checkpoints.db", "checkpoints.db-wal", "checkpoints.db-shm",
            "store.db", "store.db-wal", "store.db-shm"
        ]
        for db_file in db_files:
            db_path = PROJECT_ROOT / db_file
            if db_path.exists():
                try:
                    db_path.unlink()
                except Exception:
                    pass

    def run_eval_for_bug(self, bug_name: str) -> dict[str, Any]:
        """Run the end-to-end agent triage and patching flow for a single bug."""
        print(f"\n============================================================")
        print(f"🚦 STARTING EVALUATION FOR BUG: {bug_name}")
        print(f"============================================================")
        
        # 1. Clean previous run state
        clear_active_bug()
        db_files = [
            "checkpoints.db", "checkpoints.db-wal", "checkpoints.db-shm",
            "store.db", "store.db-wal", "store.db-shm"
        ]
        for db_file in db_files:
            db_path = PROJECT_ROOT / db_file
            if db_path.exists():
                try: db_path.unlink()
                except Exception: pass

        # Restore the buggy file to be evaluated
        bug_path = PROJECT_ROOT / "breakomatic" / "bugs" / f"{bug_name}.py"
        bug_path.write_text(self.original_contents[bug_name])
        orig_path = bug_path.with_suffix(".py.orig")
        if orig_path.exists():
            orig_path.unlink()

        # 2. Setup the incident context
        alert = generate_alert(bug_name)
        prompt = (
            f"Incident details:\n"
            f"Title: {alert.get('title')}\n"
            f"Severity: {alert.get('severity')}\n"
            f"Timestamp: {alert.get('timestamp')}\n\n"
            f"Stack Trace:\n```\n{alert.get('stack_trace')}\n```\n\n"
            f"Logs:\n" + "\n".join(alert.get("logs", [])) + "\n\n"
            f"Recent Deploys:\n" + json.dumps(alert.get("recent_deploys", []), indent=2) + "\n\n"
            f"Metrics:\n" + json.dumps(alert.get("metrics", {}), indent=2)
        )

        # 3. Build agent and config
        agent = create_orchestrator(model_name="llama-3.3-70b-versatile")
        config = {"configurable": {"thread_id": f"eval-{bug_name}-{int(time.time())}"}}

        # 4. Invoke agent (runs until interrupt)
        print("🤖 Invoking agent (Phase 1)...")
        agent.invoke(
            {
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
            },
            config=config,
        )

        # 5. Check if it hit the human gate interrupt before diagnose
        state = agent.get_state(config)
        if state.next and state.next[0] == "approval_gate":
            print("💾 Hit approval gate checkpoint. Simulating automated harness approval...")
            agent.invoke(None, config=config)
            # After approval_gate runs, check if we need to continue to diagnose
            state2 = agent.get_state(config)
            if state2.next:
                agent.invoke(None, config=config)

        # 6. Retrieve final state values
        final_state = agent.get_state(config).values
        selected_bug = final_state.get("selected_bug")
        patch_result = final_state.get("patch_result", "")
        
        # 7. Evaluate success
        success = False
        reason = ""
        
        if selected_bug != bug_name:
            reason = f"Agent selected wrong bug: expected {bug_name}, got {selected_bug}"
        elif "failed" in patch_result.lower() or "error" in patch_result.lower():
            reason = f"Patch writer sandbox tests failed:\n{patch_result}"
        elif "1 passed" not in patch_result and "passed" not in patch_result.lower():
            reason = f"No passing test execution output found in patch result:\n{patch_result}"
        else:
            success = True
            reason = "Bug successfully identified, reproduced, patched, and verified by regression test suite."

        print(f"\n🏁 Finished {bug_name}. Success: {success}. Reason: {reason}")
        return {
            "bug": bug_name,
            "success": success,
            "selected_bug": selected_bug,
            "reason": reason,
        }

def main():
    harness = EvalHarness()
    results = []
    
    try:
        for bug in BUGS:
            try:
                res = harness.run_eval_for_bug(bug)
                results.append(res)
            except Exception as e:
                print(f"💥 Exception running evaluation for {bug}: {e}")
                results.append({
                    "bug": bug,
                    "success": False,
                    "selected_bug": "error",
                    "reason": f"Harness run exception: {e}",
                })
    finally:
        harness.restore_all_files()

    print("\n" + "=" * 60)
    print("📊 EVALUATION RESULTS SUMMARY")
    print("=" * 60)
    passed_count = sum(1 for r in results if r["success"])
    for r in results:
        status = "✅ PASS" if r["success"] else "❌ FAIL"
        print(f"{r['bug']:-<30} {status} (Identified as: {r['selected_bug']})")
        if not r["success"]:
            print(f"   Reason: {r['reason']}")
    print("-" * 60)
    print(f"Total: {passed_count}/{len(BUGS)} passed.")
    print("=" * 60)
    
    sys.exit(0 if passed_count >= 4 else 1)

if __name__ == "__main__":
    main()
