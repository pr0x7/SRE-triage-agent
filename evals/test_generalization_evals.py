"""
Generalization Evaluation Benchmark Test Runner (Phase 20).
"""
import pytest
from evals.generalization_harness import GeneralizationEvalHarness


def test_generalization_benchmark_pass_rate():
    """Verify that the agent successfully profiles and patches external Python repositories."""
    harness = GeneralizationEvalHarness()
    report = harness.run_all_benchmarks()

    print(f"\n============================================================")
    print(f"📊 GENERALIZATION EVAL BENCHMARK RESULTS")
    print(f"============================================================")
    print(f"Pass Rate: {report['pass_rate_quote']}")
    for r in report["results"]:
        status = "✅ PASS" if r["success"] else "❌ FAIL"
        print(f"{status} | Repo: {r['repo']:<20} | Bug: {r['bug_type']}")

    assert report["passed_repos"] == report["total_repos"], (
        f"Generalization eval failed: expected 100% pass rate, got {report['pass_rate_quote']}"
    )
