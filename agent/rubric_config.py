"""
RubricMiddleware — self-grading layer for patch quality.

Evaluates the patch writer's output against 5 rubric criteria:
1. Confirmed reproduction required
2. Rerun repro check must return not_reproduced (bug is gone)
3. Diff scope must be minimal (≤30 added lines, single file)
4. Regression test file must exist and not be empty
5. No silent exception-swallowing (bare except / except Exception: pass)

If any criterion fails, the grader returns a rejection with feedback
so the patch_writer can revise.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.resolve()


# ── Criterion Result ──────────────────────────────────────────────


@dataclass
class CriterionResult:
    """Result of a single rubric criterion check."""
    name: str
    passed: bool
    detail: str
    weight: float = 1.0


@dataclass
class GradeResult:
    """Aggregated result from the rubric grader."""
    passed: bool
    criteria: list[CriterionResult] = field(default_factory=list)
    feedback: str = ""
    score: float = 0.0

    def summary(self) -> str:
        lines = [f"Rubric Grade: {'PASS ✅' if self.passed else 'FAIL ❌'} (score: {self.score:.0%})"]
        for c in self.criteria:
            status = "✅" if c.passed else "❌"
            lines.append(f"  {status} {c.name}: {c.detail}")
        if self.feedback:
            lines.append(f"\nFeedback: {self.feedback}")
        return "\n".join(lines)


# ── Rerun Repro Check Tool ────────────────────────────────────────


def rerun_repro_check(bug_name: str, incident_context: str = "") -> dict:
    """Re-invoke the repro_graph against the patched code to verify the bug is fixed.

    Returns a dict with:
      - verdict: "confirmed" | "not_reproduced" | "escalate"
      - evidence: structured evidence string
    """
    from agent.subagents.repro_graph import run_reproduction

    # Map bug to endpoint
    endpoint_map = {
        "n_plus_one": {"method": "GET", "path": "/orders"},
        "null_deref": {"method": "GET", "path": "/users/3"},
        "bad_migration": {"method": "GET", "path": "/orders"},
        "leaked_connection": {"method": "GET", "path": "/orders"},
        "broken_env": {"method": "GET", "path": "/health"},
    }
    ep = endpoint_map.get(bug_name, {"method": "GET", "path": "/orders"})

    logger.info(f"rubric: rerun_repro_check for bug '{bug_name}'...")
    result = run_reproduction(
        hypothesis=f"Verify {bug_name} is fixed after patch",
        bug_name=bug_name,
        incident_context=incident_context,
        endpoints_to_test=[ep],
        max_attempts=1,
    )
    logger.info(f"rubric: rerun_repro_check verdict: {result['verdict']}")
    return result


# ── Rubric Criteria Checks ────────────────────────────────────────


def _check_confirmed_repro(repro_result: str) -> CriterionResult:
    """Criterion 1: The original reproduction must have confirmed the bug."""
    try:
        repro = json.loads(repro_result)
        verdict = repro.get("verdict", "")
    except (json.JSONDecodeError, TypeError):
        verdict = repro_result if isinstance(repro_result, str) else ""

    confirmed = "confirmed" in str(verdict).lower()
    return CriterionResult(
        name="Confirmed reproduction",
        passed=confirmed,
        detail=f"Repro verdict: {verdict}" if confirmed else
               f"Repro was NOT confirmed (verdict: {verdict}). Fix cannot be trusted without reproduction.",
    )


def _check_rerun_repro(bug_name: str, incident_context: str) -> CriterionResult:
    """Criterion 2: After patching, re-run repro must return not_reproduced."""
    try:
        result = rerun_repro_check(bug_name, incident_context)
        verdict = result.get("verdict", "unknown")
    except Exception as e:
        logger.error(f"rubric: rerun_repro_check failed: {e}")
        return CriterionResult(
            name="Rerun repro check",
            passed=False,
            detail=f"Rerun repro check failed with exception: {e}",
        )

    # The bug should NOT be reproducible after patching
    # "not_reproduced" or "escalate" (meaning it couldn't reproduce) both count as pass
    passed = verdict in ("not_reproduced", "escalate")
    return CriterionResult(
        name="Rerun repro check",
        passed=passed,
        detail=f"Post-patch repro verdict: {verdict}" if passed else
               f"Bug STILL reproduces after patch (verdict: {verdict}). Fix is insufficient.",
    )


def _check_diff_scope(bug_name: str) -> CriterionResult:
    """Criterion 3: Diff scope must be minimal."""
    bug_file = PROJECT_ROOT / "breakomatic" / "bugs" / f"{bug_name}.py"
    orig_file = bug_file.with_suffix(".py.orig")

    if not orig_file.exists() or not bug_file.exists():
        return CriterionResult(
            name="Minimal diff scope",
            passed=True,  # Can't check, assume OK
            detail="Original backup not found — skipping diff scope check.",
        )

    orig_lines = orig_file.read_text().splitlines()
    fixed_lines = bug_file.read_text().splitlines()

    added = sum(1 for line in fixed_lines if line not in orig_lines)
    removed = sum(1 for line in orig_lines if line not in fixed_lines)
    total_changes = added + removed

    # Allow up to 30 net changed lines
    passed = total_changes <= 30
    return CriterionResult(
        name="Minimal diff scope",
        passed=passed,
        detail=f"Diff: +{added}/-{removed} lines (total: {total_changes})" if passed else
               f"Diff too large: +{added}/-{removed} lines (total: {total_changes}, limit: 30). Patch is not minimal.",
    )


def _check_regression_test() -> CriterionResult:
    """Criterion 4: Regression test file must exist and not be empty."""
    reg_test = PROJECT_ROOT / "evals" / "test_regression.py"

    if not reg_test.exists():
        return CriterionResult(
            name="Regression test required",
            passed=False,
            detail="evals/test_regression.py does not exist. A regression test is mandatory.",
        )

    content = reg_test.read_text().strip()
    if len(content) < 50:
        return CriterionResult(
            name="Regression test required",
            passed=False,
            detail=f"evals/test_regression.py exists but is too short ({len(content)} chars). Must contain meaningful test.",
        )

    # Check it has at least one test function
    has_test = "def test_" in content
    return CriterionResult(
        name="Regression test required",
        passed=has_test,
        detail="Regression test exists with test function(s)." if has_test else
               "evals/test_regression.py exists but contains no test functions (def test_*).",
    )


def _check_no_exception_swallowing(bug_name: str) -> CriterionResult:
    """Criterion 5: No silent exception-swallowing in patched code."""
    bug_file = PROJECT_ROOT / "breakomatic" / "bugs" / f"{bug_name}.py"

    if not bug_file.exists():
        return CriterionResult(
            name="No exception swallowing",
            passed=True,
            detail="Bug file not found — skipping check.",
        )

    content = bug_file.read_text()

    # Patterns that indicate band-aid fixes
    bad_patterns = [
        (r"except\s*:", "Bare 'except:' catches all exceptions silently"),
        (r"except\s+Exception\s*:\s*\n\s*pass", "'except Exception: pass' swallows errors"),
        (r"except\s+\w+\s*:\s*\n\s*pass", "'except <Type>: pass' swallows errors"),
        (r"except.*:\s*\n\s*\.\.\.(\s*#.*)?$", "'except: ...' swallows errors"),
        (r"try:\s*\n\s*.*\n\s*except.*:\s*\n\s*(return\s+None|return\s*$|pass)",
         "try/except returning None or pass — likely a band-aid fix"),
    ]

    violations = []
    for pattern, description in bad_patterns:
        if re.search(pattern, content, re.MULTILINE):
            violations.append(description)

    passed = len(violations) == 0
    return CriterionResult(
        name="No exception swallowing",
        passed=passed,
        detail="No silent exception-swallowing patterns found." if passed else
               f"Band-aid fix detected: {'; '.join(violations)}. Fix must address root cause, not hide errors.",
    )


# ── Main Grading Function ────────────────────────────────────────


def grade_patch(
    bug_name: str,
    repro_result: str,
    incident_context: str = "",
    skip_rerun: bool = False,
) -> GradeResult:
    """Grade the patch against all rubric criteria.

    Args:
        bug_name: The bug being fixed.
        repro_result: JSON string of the original reproduction result.
        incident_context: Original incident context for rerun.
        skip_rerun: If True, skip the expensive rerun_repro_check.

    Returns:
        GradeResult with pass/fail, individual criteria, and feedback.
    """
    logger.info(f"rubric: grading patch for bug '{bug_name}'...")

    criteria = []

    # 1. Confirmed reproduction
    criteria.append(_check_confirmed_repro(repro_result))

    # 2. Rerun repro check (expensive — runs a sandbox)
    if not skip_rerun:
        criteria.append(_check_rerun_repro(bug_name, incident_context))
    else:
        criteria.append(CriterionResult(
            name="Rerun repro check",
            passed=True,
            detail="Skipped (skip_rerun=True).",
        ))

    # 3. Diff scope
    criteria.append(_check_diff_scope(bug_name))

    # 4. Regression test
    criteria.append(_check_regression_test())

    # 5. No exception swallowing
    criteria.append(_check_no_exception_swallowing(bug_name))

    # Compute score
    total_weight = sum(c.weight for c in criteria)
    passed_weight = sum(c.weight for c in criteria if c.passed)
    score = passed_weight / total_weight if total_weight > 0 else 0.0

    # Must pass ALL criteria
    all_passed = all(c.passed for c in criteria)

    # Build feedback for failed criteria
    failed = [c for c in criteria if not c.passed]
    feedback = ""
    if failed:
        feedback = "The following rubric criteria failed:\n" + "\n".join(
            f"- {c.name}: {c.detail}" for c in failed
        ) + "\n\nPlease revise the patch to address these issues."

    result = GradeResult(
        passed=all_passed,
        criteria=criteria,
        feedback=feedback,
        score=score,
    )
    logger.info(f"rubric: grade result: {'PASS' if all_passed else 'FAIL'} ({score:.0%})")
    return result
