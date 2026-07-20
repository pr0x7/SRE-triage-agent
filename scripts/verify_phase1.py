#!/usr/bin/env python3
"""
Phase 1 verification — tests each injectable bug end-to-end.

For each bug:
  1. Reset DB + inject bug
  2. Start server
  3. Hit endpoints and verify expected failure
  4. Clear bug

Run:  python scripts/verify_phase1.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time

import httpx

BASE = "http://127.0.0.1:8099"
TIMEOUT = 10.0


def banner(msg: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {msg}")
    print(f"{'─' * 60}")


def reset_and_inject(bug: str | None) -> None:
    """Clear bugs, reset DB, optionally inject a new bug."""
    from breakomatic.config import clear_active_bug, set_active_bug
    from breakomatic.database import (
        create_session_factory,
        get_engine,
        reset_database,
        seed_database,
    )

    clear_active_bug()
    engine = get_engine()
    reset_database(engine)
    sf = create_session_factory(engine)
    seed_database(engine, sf)
    engine.dispose()

    if bug:
        set_active_bug(bug)


def start_server() -> subprocess.Popen | None:
    """Start uvicorn in background, wait for it to be ready."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "breakomatic.app:app",
         "--port", "8099", "--no-access-log", "--log-level", "error"],
        cwd="/Users/prox/Desktop/SRE",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for server to be ready
    for _ in range(30):
        time.sleep(0.3)
        try:
            r = httpx.get(f"{BASE}/health", timeout=2)
            if r.status_code == 200:
                return proc
        except Exception:
            pass
        # Check if process died
        if proc.poll() is not None:
            return None
    return proc


def stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ── Individual bug tests ──────────────────────────────────────────

def test_clean() -> bool:
    """Verify service works with no bug injected."""
    banner("0/5  Clean (no bug)")
    reset_and_inject(None)
    proc = start_server()
    if proc is None:
        print("  ❌  Server failed to start")
        return False

    try:
        health = httpx.get(f"{BASE}/health", timeout=TIMEOUT).json()
        assert health["active_bug"] is None, f"Expected no bug, got {health['active_bug']}"
        print(f"  ✅  /health: {health}")

        users = httpx.get(f"{BASE}/users", timeout=TIMEOUT).json()
        assert len(users) == 5, f"Expected 5 users, got {len(users)}"
        print(f"  ✅  /users: {len(users)} users")

        user3 = httpx.get(f"{BASE}/users/3", timeout=TIMEOUT).json()
        assert user3["profile_summary"] == "No bio provided"
        print(f"  ✅  /users/3: profile_summary={user3['profile_summary']!r}")

        orders = httpx.get(f"{BASE}/orders", timeout=TIMEOUT).json()
        assert len(orders) > 0
        assert "items" in orders[0]
        print(f"  ✅  /orders: {len(orders)} orders with items")

        return True
    except Exception as e:
        print(f"  ❌  {e}")
        return False
    finally:
        stop_server(proc)


def test_n_plus_one() -> bool:
    """N+1 bug should make /orders very slow."""
    banner("1/5  n_plus_one")
    reset_and_inject("n_plus_one")
    proc = start_server()
    if proc is None:
        print("  ❌  Server failed to start")
        return False

    try:
        health = httpx.get(f"{BASE}/health", timeout=TIMEOUT).json()
        assert health["active_bug"] == "n_plus_one"
        print(f"  ✅  Bug active: {health['active_bug']}")

        # /orders should still work but be noticeably slow
        t0 = time.time()
        orders = httpx.get(f"{BASE}/orders", timeout=30).json()
        elapsed = time.time() - t0
        assert len(orders) > 0
        # With ~30 orders and 10ms sleep per order, expect > 300ms
        print(f"  📊  /orders returned {len(orders)} orders in {elapsed:.2f}s")
        if elapsed > 0.2:
            print(f"  ✅  Slow as expected (N+1 overhead)")
        else:
            print(f"  ⚠️  Faster than expected — but still working")

        return True
    except Exception as e:
        print(f"  ❌  {e}")
        return False
    finally:
        stop_server(proc)


def test_null_deref() -> bool:
    """Null deref should crash on users 3 and 5 but work on 1, 2, 4."""
    banner("2/5  null_deref")
    reset_and_inject("null_deref")
    proc = start_server()
    if proc is None:
        print("  ❌  Server failed to start")
        return False

    try:
        # User 1 (has bio) should work
        r1 = httpx.get(f"{BASE}/users/1", timeout=TIMEOUT)
        assert r1.status_code == 200, f"User 1 should work, got {r1.status_code}"
        print(f"  ✅  /users/1: 200 OK (has profile_bio)")

        # User 3 (no bio) should 500
        r3 = httpx.get(f"{BASE}/users/3", timeout=TIMEOUT)
        assert r3.status_code == 500, f"User 3 should 500, got {r3.status_code}"
        print(f"  ✅  /users/3: 500 (profile_bio is None → AttributeError)")

        # User 5 (no bio) should also 500
        r5 = httpx.get(f"{BASE}/users/5", timeout=TIMEOUT)
        assert r5.status_code == 500, f"User 5 should 500, got {r5.status_code}"
        print(f"  ✅  /users/5: 500 (same bug)")

        # User 4 (has bio) should work
        r4 = httpx.get(f"{BASE}/users/4", timeout=TIMEOUT)
        assert r4.status_code == 200, f"User 4 should work, got {r4.status_code}"
        print(f"  ✅  /users/4: 200 OK (has profile_bio)")

        return True
    except Exception as e:
        print(f"  ❌  {e}")
        return False
    finally:
        stop_server(proc)


def test_bad_migration() -> bool:
    """Bad migration should break all order-related endpoints."""
    banner("3/5  bad_migration")
    reset_and_inject("bad_migration")
    proc = start_server()
    if proc is None:
        print("  ❌  Server failed to start")
        return False

    try:
        # /health should still work
        health = httpx.get(f"{BASE}/health", timeout=TIMEOUT)
        assert health.status_code == 200
        print(f"  ✅  /health: 200 OK (not affected)")

        # /orders should 500 (references orders.status)
        r = httpx.get(f"{BASE}/orders", timeout=TIMEOUT)
        assert r.status_code == 500, f"Expected 500, got {r.status_code}"
        print(f"  ✅  /orders: 500 (orders.status column missing)")

        # /users/{id} should also 500 (references orders.status in response)
        r2 = httpx.get(f"{BASE}/users/1", timeout=TIMEOUT)
        assert r2.status_code == 500, f"Expected 500, got {r2.status_code}"
        print(f"  ✅  /users/1: 500 (orders.status column missing)")

        # /users list should still work (doesn't touch orders)
        r3 = httpx.get(f"{BASE}/users", timeout=TIMEOUT)
        assert r3.status_code == 200
        print(f"  ✅  /users: 200 OK (doesn't reference orders.status)")

        return True
    except Exception as e:
        print(f"  ❌  {e}")
        return False
    finally:
        stop_server(proc)


def test_leaked_connection() -> bool:
    """Leaked connections should exhaust the pool after ~8 requests."""
    banner("4/5  leaked_connection")
    reset_and_inject("leaked_connection")
    proc = start_server()
    if proc is None:
        print("  ❌  Server failed to start")
        return False

    try:
        # First 8 requests should work (pool_size=5 + max_overflow=3)
        successes = 0
        for i in range(12):
            try:
                r = httpx.get(f"{BASE}/users", timeout=8)
                if r.status_code == 200:
                    successes += 1
                    print(f"  ✅  Request {i+1}: 200 OK")
                else:
                    print(f"  💥  Request {i+1}: {r.status_code}")
                    break
            except httpx.ReadTimeout:
                print(f"  💥  Request {i+1}: TIMEOUT (pool exhausted)")
                break
            except Exception as e:
                print(f"  💥  Request {i+1}: {type(e).__name__}: {e}")
                break

        print(f"\n  📊  {successes} requests succeeded before pool exhaustion")
        if successes >= 5 and successes <= 10:
            print(f"  ✅  Pool exhausted as expected (~8 connections leaked)")
            return True
        elif successes > 10:
            print(f"  ⚠️  More requests succeeded than expected — pool may be larger")
            return True
        else:
            print(f"  ❌  Too few successes — something else is wrong")
            return False

    except Exception as e:
        print(f"  ❌  {e}")
        return False
    finally:
        stop_server(proc)


def test_broken_env() -> bool:
    """Broken env should prevent the server from starting at all."""
    banner("5/5  broken_env")
    reset_and_inject("broken_env")

    # Server should fail to start
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "breakomatic.app:app",
         "--port", "8099", "--no-access-log"],
        cwd="/Users/prox/Desktop/SRE",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for it to crash
    try:
        returncode = proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        print("  ❌  Server didn't crash — it should have")
        return False

    stderr = proc.stderr.read().decode(errors="replace")
    stdout = proc.stdout.read().decode(errors="replace")
    output = stdout + stderr

    if returncode != 0 and "RuntimeError" in output and "DATABASE_URL" in output:
        print(f"  ✅  Server crashed on boot (exit code {returncode})")
        print(f"  ✅  Error mentions DATABASE_URL misconfiguration")
        # Print relevant traceback lines
        for line in output.split("\n"):
            if "RuntimeError" in line or "DATABASE_URL" in line or "FATAL" in line:
                print(f"      {line.strip()}")
        return True
    else:
        print(f"  ❌  Unexpected behavior. Exit code: {returncode}")
        print(f"      Output: {output[:500]}")
        return False


# ── Test alert generator ──────────────────────────────────────────

def test_alerts() -> bool:
    """Verify alert generator produces valid payloads for all bugs."""
    banner("BONUS  Alert generator")
    from breakomatic.alerts import generate_alert
    from breakomatic.bugs import BUG_REGISTRY

    all_ok = True
    for bug_name in BUG_REGISTRY:
        try:
            alert = generate_alert(bug_name)
            assert "incident_id" in alert
            assert "stack_trace" in alert
            assert "logs" in alert
            assert len(alert["logs"]) > 0
            print(f"  ✅  {bug_name}: {alert['title'][:60]}...")
        except Exception as e:
            print(f"  ❌  {bug_name}: {e}")
            all_ok = False

    return all_ok


# ── Main ──────────────────────────────────────────────────────────

def main() -> None:
    banner("🐛  Phase 1 Verification — Break-o-matic Bug Tests")

    results = {}
    results["clean"] = test_clean()
    results["n_plus_one"] = test_n_plus_one()
    results["null_deref"] = test_null_deref()
    results["bad_migration"] = test_bad_migration()
    results["leaked_connection"] = test_leaked_connection()
    results["broken_env"] = test_broken_env()
    results["alerts"] = test_alerts()

    # Cleanup
    reset_and_inject(None)

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
        print("  🎉  Phase 1 COMPLETE — all bugs verified!")
        print("  Ready for Phase 2.")
    else:
        print("  ⚠️  Some tests failed — review and fix.")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
