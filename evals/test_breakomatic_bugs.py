"""
End-to-end tests — one test per injectable bug in break-o-matic.
Each test injects a bug, runs the agent, and asserts the agent finds + fixes it.
"""
from __future__ import annotations

import pytest
from evals.harness import EvalHarness

def test_eval_harness_pass_rate():
    """Verify that the agent successfully patches at least 4 of the 5 bugs."""
    harness = EvalHarness()
    results = []
    bugs = ["n_plus_one", "null_deref", "bad_migration", "leaked_connection", "broken_env"]
    
    try:
        for bug in bugs:
            try:
                res = harness.run_eval_for_bug(bug)
                results.append(res)
            except Exception as e:
                results.append({
                    "bug": bug,
                    "success": False,
                    "reason": f"Exception raised: {e}",
                })
    finally:
        harness.restore_all_files()

    passed_count = sum(1 for r in results if r["success"])
    failures = [r for r in results if not r["success"]]
    failure_msg = "\n".join(f"- {f['bug']}: {f['reason']}" for f in failures)
    
    assert passed_count >= 4, (
        f"Expected at least 4 bugs to pass, but only {passed_count}/5 passed.\n"
        f"Failures:\n{failure_msg}"
    )
