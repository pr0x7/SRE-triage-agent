#!/usr/bin/env python3
"""
Phase 0 verification script.
Checks that all dependencies import correctly, Docker is running,
and the DockerSandbox can provision → execute → tear down a container.

Run:  python scripts/verify_phase0.py
Done when: this script exits 0 with all checks green.
"""
from __future__ import annotations

import sys
import time


def banner(msg: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {msg}")
    print(f"{'─' * 60}")


def check_imports() -> bool:
    """Verify all core dependencies can be imported."""
    banner("1/4  Checking imports")
    failures = []

    checks = [
        ("deepagents", "import deepagents"),
        ("langgraph", "import langgraph"),
        ("langchain_groq", "import langchain_groq"),
        ("fastapi", "import fastapi"),
        ("sqlalchemy", "import sqlalchemy"),
        ("pydantic", "import pydantic"),
        ("docker", "import docker"),
        ("pytest", "import pytest"),
        ("httpx", "import httpx"),
        ("rich", "import rich"),
    ]

    for name, stmt in checks:
        try:
            exec(stmt)  # noqa: S102
            print(f"  ✅  {name}")
        except ImportError as e:
            print(f"  ❌  {name} — {e}")
            failures.append(name)

    if failures:
        print(f"\n  ⚠️  Missing packages: {', '.join(failures)}")
        print("  Run:  pip install -e '.[dev]'")
        return False
    print("\n  All imports OK ✅")
    return True


def check_docker_daemon() -> bool:
    """Verify the Docker daemon is reachable."""
    banner("2/4  Checking Docker daemon")
    try:
        import docker
        client = docker.from_env()
        info = client.info()
        print(f"  ✅  Docker daemon running")
        print(f"      Server version: {info.get('ServerVersion', '?')}")
        print(f"      Containers: {info.get('Containers', '?')}")
        return True
    except Exception as e:
        print(f"  ❌  Cannot connect to Docker: {e}")
        print("  Make sure Docker Desktop or Docker Engine is running.")
        return False


def check_sandbox_lifecycle() -> bool:
    """Provision a DockerSandbox, run 'echo hi', tear it down."""
    banner("3/4  Testing DockerSandbox lifecycle")

    # Import from our project
    sys.path.insert(0, ".")
    from agent.docker_sandbox import DockerSandbox

    sandbox = DockerSandbox(image="python:3.11-slim")
    try:
        print("  ⏳  Starting container...")
        t0 = time.time()
        sandbox.start()
        print(f"  ✅  Container started: {sandbox.id}  ({time.time() - t0:.1f}s)")

        print("  ⏳  Running 'echo hello from sandbox'...")
        result = sandbox.execute("echo hello from sandbox")
        output = result.output.strip()
        print(f"  📤  stdout: {output!r}")
        print(f"  📤  exit_code: {result.exit_code}")

        if result.exit_code != 0:
            print(f"  ❌  Non-zero exit code: {result.exit_code}")
            return False

        if "hello from sandbox" not in output:
            print(f"  ❌  Expected 'hello from sandbox' in output, got: {output!r}")
            return False

        print("  ✅  Command executed successfully")

        # Bonus: verify Python works inside the container
        print("  ⏳  Running 'python3 --version'...")
        py_result = sandbox.execute("python3 --version")
        print(f"  📤  {py_result.output.strip()}")
        print("  ✅  Python available in sandbox")

        return True

    except Exception as e:
        print(f"  ❌  Sandbox test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        print("  ⏳  Tearing down container...")
        sandbox.stop()
        print("  ✅  Container removed")


def check_project_structure() -> bool:
    """Quick sanity check that the repo skeleton is in place."""
    banner("4/4  Checking project structure")
    from pathlib import Path

    expected = [
        "pyproject.toml",
        ".env.example",
        "agent/__init__.py",
        "agent/docker_sandbox.py",
        "agent/orchestrator.py",
        "agent/memory.py",
        "agent/fanout.py",
        "agent/approval.py",
        "agent/rubric_config.py",
        "agent/subagents/__init__.py",
        "agent/subagents/log_analyzer.py",
        "agent/subagents/deploy_diff.py",
        "agent/subagents/db_inspector.py",
        "agent/subagents/repro_graph.py",
        "agent/subagents/patch_writer.py",
        "breakomatic/__init__.py",
        "breakomatic/app.py",
        "breakomatic/models.py",
        "breakomatic/inject.py",
        "breakomatic/bugs/__init__.py",
        "breakomatic/bugs/n_plus_one.py",
        "breakomatic/bugs/null_deref.py",
        "breakomatic/bugs/bad_migration.py",
        "breakomatic/bugs/leaked_connection.py",
        "breakomatic/bugs/broken_env.py",
        "incidents/sample_n_plus_one.json",
        "evals/test_breakomatic_bugs.py",
        "evals/harness.py",
        "dashboard/app.py",
        "scripts/run_incident.py",
        "scripts/seed_bug.py",
    ]

    missing = [f for f in expected if not Path(f).exists()]

    if missing:
        print(f"  ❌  Missing files:")
        for f in missing:
            print(f"      • {f}")
        return False

    print(f"  ✅  All {len(expected)} expected files present")
    return True


def main() -> None:
    banner("🚨 SRE Agent — Phase 0 Verification")

    results = {
        "imports": check_imports(),
        "docker": check_docker_daemon(),
        "sandbox": False,  # only attempt if docker is up
        "structure": check_project_structure(),
    }

    # Only test sandbox if Docker daemon is reachable
    if results["docker"]:
        results["sandbox"] = check_sandbox_lifecycle()
    else:
        banner("3/4  Skipping sandbox test (Docker not available)")
        print("  ⏭️  Fix Docker first, then re-run.")

    # Summary
    banner("📊  Results")
    all_pass = True
    for name, passed in results.items():
        icon = "✅" if passed else "❌"
        print(f"  {icon}  {name}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print("  🎉  Phase 0 COMPLETE — all checks passed!")
        print("  Ready for Phase 1.")
    else:
        print("  ⚠️  Some checks failed — fix and re-run.")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
