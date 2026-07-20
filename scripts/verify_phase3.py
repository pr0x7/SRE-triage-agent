#!/usr/bin/env python3
"""
Phase 3 verification script.
Starts a DockerSandbox, uploads the breakomatic codebase, deploys it clean,
sends a query, redeploys with 'null_deref' bug, queries user 3 to verify the failure,
and clean-stops the container.

Run:  python scripts/verify_phase3.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.docker_sandbox import DockerSandbox
from agent.sandbox_tools import DeployBreakomaticTool, QueryBreakomaticTool


def banner(msg: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {msg}")
    print(f"{'─' * 60}")


def main() -> None:
    banner("🚨 SRE Agent — Phase 3 Verification (Sandbox Wiring)")

    print("⏳  Initializing and starting DockerSandbox...")
    sandbox = DockerSandbox(image="python:3.11-slim")
    try:
        sandbox.start()
        print(f"✅  Sandbox container started: {sandbox.id}")

        # Instantiate the tools directly
        deploy_tool = DeployBreakomaticTool(sandbox=sandbox)
        query_tool = QueryBreakomaticTool(sandbox=sandbox)

        # ── Test 1: Clean Deployment ─────────────────────────────
        banner("1/3 Testing Clean Deploy")
        print("⏳  Deploying breakomatic without bugs...")
        t0 = time.time()
        deploy_res = deploy_tool._run(bug_name=None)
        print(f"📤  Deploy Result: {deploy_res}")
        print(f"⏱️  Deploy took {time.time() - t0:.1f}s")

        if "health" not in deploy_res.lower() or "ok" not in deploy_res.lower():
            print("❌  Deployment verification failed")
            sys.exit(1)

        print("\n⏳  Querying /users endpoint...")
        users_res = query_tool._run(method="GET", path="/users")
        print(f"📤  /users response:\n{users_res}")
        if "Alice Johnson" not in users_res:
            print("❌  Failed to list users from clean database")
            sys.exit(1)
        print("✅  Clean deploy query successful")

        # ── Test 2: Bug Injection Deployment (null_deref) ──────────
        banner("2/3 Testing Bug Injection Deploy (null_deref)")
        print("⏳  Deploying breakomatic with 'null_deref' bug...")
        t0 = time.time()
        deploy_bug_res = deploy_tool._run(bug_name="null_deref")
        print(f"📤  Deploy Result: {deploy_bug_res}")
        print(f"⏱️  Deploy took {time.time() - t0:.1f}s")

        print("\n⏳  Querying /users/1 (should succeed)...")
        user1_res = query_tool._run(method="GET", path="/users/1")
        print(f"📤  /users/1 response: {user1_res}")
        if "Alice Johnson" not in user1_res:
            print("❌  User 1 query failed under bug conditions")
            sys.exit(1)

        print("\n⏳  Querying /users/3 (should 500 under null_deref)...")
        user3_res = query_tool._run(method="GET", path="/users/3")
        print(f"📤  /users/3 response: {user3_res}")
        if '"status": 500' not in user3_res:
            print("❌  Expected user 3 to return a 500 response, but it succeeded or failed incorrectly")
            sys.exit(1)
        print("✅  Bug injection verification successful")

        # ── Test 3: Sandbox File Persistence ──────────────────────
        banner("3/3 Testing Sandbox File Persistence")
        print("⏳  Checking active bug configuration file inside sandbox...")
        active_bug_file = sandbox.execute("cat breakomatic/.active_bug.json")
        print(f"📤  Content of breakomatic/.active_bug.json: {active_bug_file.output.strip()}")
        if "null_deref" not in active_bug_file.output:
            print("❌  Active bug json does not contain expected config")
            sys.exit(1)
        print("✅  File persistence verification successful")

        banner("🎉 Verification Successful")
        print("All Phase 3 sandbox wiring checks passed!")

    except Exception as e:
        print(f"\n❌  Verification failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        print("\n⏳  Stopping sandbox...")
        sandbox.stop()
        print("✅  Sandbox container removed")


if __name__ == "__main__":
    main()
