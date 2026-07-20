#!/usr/bin/env python3
"""
Phase 4 verification script.
Tests the reproduction subgraph (repro_graph.py) end-to-end under both confirmation
and retry/escalation conditions, validating that the sandbox is always torn down.

Run:  python scripts/verify_phase4.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from agent.subagents.repro_graph import run_reproduction
import docker


def banner(msg: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {msg}")
    print(f"{'─' * 60}")


def count_sandbox_containers() -> int:
    """Helper to check if any deepagents containers are running."""
    client = docker.from_env()
    containers = client.containers.list(all=True)
    return len([c for c in containers if "deepagents-sandbox-" in c.name])


def main() -> None:
    banner("🚨 SRE Agent — Phase 4 Verification (Reproduction Subgraph)")

    # Ensure no stale containers exist before starting
    initial_stale_count = count_sandbox_containers()
    if initial_stale_count > 0:
        print(f"⚠️  Warning: Found {initial_stale_count} preexisting sandbox containers. Cleaning up...")
        client = docker.from_env()
        for c in client.containers.list(all=True):
            if "deepagents-sandbox-" in c.name:
                c.remove(force=True)

    # ── Test 1: Successful Reproduction (n_plus_one) ─────────────────
    banner("1/2 Testing Successful Bug Reproduction (n_plus_one)")
    print("⏳  Running reproduction subgraph for 'n_plus_one'...")
    t0 = time.time()
    
    result = run_reproduction(
        hypothesis="N+1 query pattern causing connection pool exhaustion",
        bug_name="n_plus_one",
        incident_context="GET /orders returns 500s after 250 individual SQL queries exhaust connection pool",
        endpoints_to_test=[{"method": "GET", "path": "/orders"}],
        max_attempts=2,
    )
    
    print(f"⏱️  Reproduction took {time.time() - t0:.1f}s")
    print(f"📤  Verdict: {result['verdict']}")
    print(f"📤  Evidence: {result['evidence']}")
    
    if result["verdict"] != "confirmed":
        print("❌  Failed: Expected verdict to be 'confirmed'")
        sys.exit(1)
        
    if not result["sandbox_cleaned"]:
        print("❌  Failed: Expected sandbox_cleaned to be True")
        sys.exit(1)

    # Confirm container is removed
    running_sandboxes = count_sandbox_containers()
    if running_sandboxes > 0:
        print(f"❌  Failed: Sandbox container leaked! Count: {running_sandboxes}")
        sys.exit(1)
        
    print("✅  Successful reproduction verified, sandbox cleaned up successfully")

    # ── Test 2: Escalation / Non-reproduction (no bug/wrong endpoint) ──
    banner("2/2 Testing Retry and Escalation (invalid bug)")
    print("⏳  Running reproduction subgraph with an invalid bug to test retry/escalation...")
    t0 = time.time()
    
    result_fail = run_reproduction(
        hypothesis="A nonexistent issue",
        bug_name="nonexistent_bug",  # This bug does not exist, clean deploy will run
        incident_context="GET /orders crashing",
        endpoints_to_test=[{"method": "GET", "path": "/orders"}],
        max_attempts=2,
    )
    
    print(f"⏱️  Reproduction took {time.time() - t0:.1f}s")
    print(f"📤  Verdict: {result_fail['verdict']}")
    print(f"📤  Evidence: {result_fail['evidence']}")

    # Expected to retry once, then escalate since it gets 200 OK
    if result_fail["verdict"] not in ("not_reproduced", "escalate"):
        print(f"❌  Failed: Expected verdict to be 'not_reproduced' or 'escalate', got: {result_fail['verdict']}")
        sys.exit(1)
        
    if not result_fail["sandbox_cleaned"]:
        print("❌  Failed: Expected sandbox_cleaned to be True on escalation")
        sys.exit(1)

    running_sandboxes = count_sandbox_containers()
    if running_sandboxes > 0:
        print(f"❌  Failed: Sandbox container leaked on escalation! Count: {running_sandboxes}")
        sys.exit(1)
        
    print("✅  Retry and escalation verified, sandbox cleaned up successfully")

    banner("🎉 Phase 4 Verification Successful")
    print("All Phase 4 reproduction subgraph checks passed!")


if __name__ == "__main__":
    main()
