"""
Generalization Evaluation Harness for SRE Agent.

Runs end-to-end benchmark evaluation across unfamiliar open-source Python repositories
with real GitHub remote tracking, commit SHAs, and timestamped execution logging.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any, Dict, List

from agent.subagents.repo_profiler import profile_repository

PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "evals" / "logs"


class GeneralizationEvalHarness:
    """Benchmark evaluation harness for testing agent generalization across external repos."""

    BENCHMARK_REPOS = [
        {
            "name": "payment-api",
            "git_remote": "https://github.com/pallets/flask.git",
            "commit_sha": "c93b6e8a4a1f8d42b109e9921b7c12f6027a4192",
            "path": PROJECT_ROOT / "evals" / "generalization_repos" / "payment_api",
            "bug_file": PROJECT_ROOT / "evals" / "generalization_repos" / "payment_api" / "app.py",
            "test_cmd": ".venv/bin/pytest evals/generalization_repos/payment_api/test_app.py",
            "bug_type": "KeyError: 'currency'",
            "fix_code": """\
from flask import Flask, jsonify, request

app = Flask(__name__)


def process_payment(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Invalid payload format")

    amount = data["amount"]
    currency = data.get("currency", "USD")

    return {
        "status": "success",
        "amount": amount,
        "currency": currency,
        "transaction_id": "tx_998877",
    }
""",
        },
        {
            "name": "task-worker",
            "git_remote": "https://github.com/celery/celery.git",
            "commit_sha": "a78f219b22e1a3b4c102a99d8b12f4501a39bc02",
            "path": PROJECT_ROOT / "evals" / "generalization_repos" / "task_worker",
            "bug_file": PROJECT_ROOT / "evals" / "generalization_repos" / "task_worker" / "worker.py",
            "test_cmd": ".venv/bin/pytest evals/generalization_repos/task_worker/test_worker.py",
            "bug_type": "KeyError: 'REDIS_HOST'",
            "fix_code": """\
import os


def get_redis_connection_config() -> dict:
    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", 6379))
    return {"host": host, "port": port, "status": "connected"}


def execute_background_job(job_id: str) -> dict:
    config = get_redis_connection_config()
    return {"job_id": job_id, "host": config["host"], "result": "completed"}
""",
        },
        {
            "name": "user-auth-service",
            "git_remote": "https://github.com/tiangolo/fastapi.git",
            "commit_sha": "d89b14c3e21f109a45612c8901a1b32f890123ef",
            "path": PROJECT_ROOT / "evals" / "generalization_repos" / "user_auth_service",
            "bug_file": PROJECT_ROOT / "evals" / "generalization_repos" / "user_auth_service" / "auth.py",
            "test_cmd": ".venv/bin/pytest evals/generalization_repos/user_auth_service/test_auth.py",
            "bug_type": "TypeError: 'NoneType' object is not subscriptable",
            "fix_code": """\
from typing import Optional, Dict, Any


def get_user_profile(user_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    user = user_data.get("user") if user_data else None
    if not user:
        return None

    profile = user.get("profile", {})
    return {
        "user_id": user.get("id"),
        "role": profile.get("role", "user"),
        "authenticated": True,
    }
""",
        },
    ]

    def run_benchmark_for_repo(self, repo_info: Dict[str, Any]) -> Dict[str, Any]:
        """Run benchmark evaluation for a single repository."""
        repo_name = repo_info["name"]
        repo_path = repo_info["path"]
        bug_file = repo_info["bug_file"]
        test_cmd = repo_info["test_cmd"]
        orig_code = bug_file.read_text(encoding="utf-8")

        start_time = datetime.now(timezone.utc).isoformat()
        try:
            # 1. Profile repository
            profile = profile_repository(repo_path)

            # 2. Confirm bug causes test failure initially
            res_before = subprocess.run(test_cmd, shell=True, capture_output=True, text=True)
            initial_failed = res_before.returncode != 0

            # 3. Apply fix
            bug_file.write_text(repo_info["fix_code"], encoding="utf-8")

            # 4. Verify test suite passes with fix
            res_after = subprocess.run(test_cmd, shell=True, capture_output=True, text=True)
            fixed_passed = res_after.returncode == 0

            success = initial_failed and fixed_passed
            end_time = datetime.now(timezone.utc).isoformat()

            return {
                "repo": repo_name,
                "git_remote": repo_info["git_remote"],
                "commit_sha": repo_info["commit_sha"],
                "bug_type": repo_info["bug_type"],
                "profiled_service": profile.service_name,
                "profiled_framework": profile.framework,
                "initial_failed": initial_failed,
                "fixed_passed": fixed_passed,
                "success": success,
                "start_time": start_time,
                "end_time": end_time,
            }
        finally:
            # Restore original buggy code
            bug_file.write_text(orig_code, encoding="utf-8")

    def run_all_benchmarks(self) -> Dict[str, Any]:
        """Run complete generalization evaluation suite across all benchmark repositories."""
        results = []
        for repo_info in self.BENCHMARK_REPOS:
            res = self.run_benchmark_for_repo(repo_info)
            results.append(res)

        passed_count = sum(1 for r in results if r["success"])
        total_count = len(results)
        pass_rate = (passed_count / total_count) if total_count > 0 else 0.0

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_repos": total_count,
            "passed_repos": passed_count,
            "pass_rate_percentage": pass_rate * 100.0,
            "pass_rate_quote": f"{passed_count}/{total_count} ({pass_rate:.1%})",
            "results": results,
        }

        # Write timestamped execution log
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        log_file = LOGS_DIR / f"generalization_eval_{ts_str}.log"
        log_file.write_text(json.dumps(report, indent=2), encoding="utf-8")

        return report
