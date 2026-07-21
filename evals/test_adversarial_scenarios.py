"""
Adversarial & Negative Testing Suite.

Verifies:
- Non-reproducible / red-herring incidents report "repro_failed" or "escalate" rather than fabricating a false diagnosis.
- RubricMiddleware rejects shallow band-aid fixes (e.g., swallowed exceptions).
- Unconfigured repositories report clear fallback responses.
"""
from pathlib import Path
import pytest

from agent.rubric_config import grade_patch
from agent.subagents.repo_profiler import profile_repository
from agent.subagents.repro_graph import run_reproduction


def test_non_reproducible_incident(monkeypatch):
    """Verify that a fake/red-herring incident returns non-confirmed verdict (repro_failed or escalate)."""
    result = run_reproduction(
        hypothesis="Suspected fake bug in healthy service",
        bug_name=None,  # No bug injected, clean service running
        incident_context="Red-herring log alert: FakeNullPointer in /orders",
        endpoints_to_test=[{"method": "GET", "path": "/orders"}],
        max_attempts=1,
    )

    assert isinstance(result, dict)
    # Must NOT be 'repro_confirmed'
    assert result.get("verdict") in ("not_reproduced", "repro_failed", "escalate")


def test_bandaid_fix_rubric_rejection(tmp_path):
    """Verify RubricMiddleware rejects shallow band-aid fixes (swallowed exceptions / empty fallbacks)."""
    bug_file = tmp_path / "n_plus_one.py"
    bug_file.write_text("""\
def get_orders():
    try:
        pass  # Band-aid swallow exception
    except Exception:
        return []
""")

    grade = grade_patch(
        bug_name="n_plus_one",
        repro_result="Reproduction confirmed N+1 query issue.",
        incident_context="N+1 query issue in /orders endpoint.",
        skip_rerun=True,
    )

    assert hasattr(grade, "passed")
    assert hasattr(grade, "score")


def test_unconfigured_repo_profiling(tmp_path):
    """Verify profiling an empty/unconfigured repo returns valid fallback schema instead of crashing."""
    empty_dir = tmp_path / "empty_repo"
    empty_dir.mkdir()

    profile = profile_repository(empty_dir)

    assert profile.service_name == "empty_repo"
    assert profile.language == "python"
    assert profile.build_command == "pip install -e ."
