"""
Synthetic alert generator.
Given an injected bug name, produces a realistic incident payload:
  - Stack trace
  - Timestamped log lines
  - Recent deploy info
  - Metrics snapshot

This is the actual input the SRE agent receives.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def generate_alert(bug_name: str) -> dict:
    """Generate a realistic incident alert for the given bug type."""
    generators = {
        "n_plus_one": _n_plus_one_alert,
        "null_deref": _null_deref_alert,
        "bad_migration": _bad_migration_alert,
        "leaked_connection": _leaked_connection_alert,
        "broken_env": _broken_env_alert,
    }
    gen = generators.get(bug_name)
    if gen is None:
        raise ValueError(f"Unknown bug: {bug_name!r}")
    return gen()


def _ts(offset_seconds: int = 0) -> str:
    """Generate an ISO timestamp offset from 'now'."""
    from datetime import timedelta
    t = datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── N+1 Query ────────────────────────────────────────────────────────

def _n_plus_one_alert() -> dict:
    return {
        "incident_id": "INC-2025-001",
        "service": "breakomatic",
        "severity": "P1",
        "timestamp": _ts(120),
        "title": "GET /orders endpoint returning 504 Gateway Timeout",
        "stack_trace": (
            "Traceback (most recent call last):\n"
            '  File "/app/breakomatic/app.py", line 89, in list_orders\n'
            "    orders = db.query(Order).all()\n"
            '  File "/app/breakomatic/app.py", line 95, in list_orders\n'
            "    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()\n"
            '  File "/app/.venv/lib/python3.11/site-packages/sqlalchemy/engine/default.py", line 608, in execute\n'
            "    cursor.execute(statement, parameters)\n"
            "sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 3 reached, "
            "connection timed out, timeout 5.00 (Background on this error at: "
            "https://sqlalche.me/e/20/3o7r)"
        ),
        "logs": [
            f"{_ts(0)} [INFO] GET /orders - request started",
            f"{_ts(0)} [DEBUG] SELECT orders.id, orders.user_id, orders.total, orders.status FROM orders",
            f"{_ts(1)} [DEBUG] SELECT order_items.* FROM order_items WHERE order_items.order_id = 1",
            f"{_ts(1)} [DEBUG] SELECT order_items.* FROM order_items WHERE order_items.order_id = 2",
            f"{_ts(1)} [DEBUG] SELECT order_items.* FROM order_items WHERE order_items.order_id = 3",
            f"{_ts(2)} [DEBUG] SELECT order_items.* FROM order_items WHERE order_items.order_id = 4",
            f"{_ts(2)} [DEBUG] ... (26 more individual item queries)",
            f"{_ts(90)} [WARN] Request latency exceeded 30s threshold: GET /orders",
            f"{_ts(115)} [ERROR] Connection pool exhausted - 8/8 connections in use, 0 available",
            f"{_ts(120)} [ERROR] 504 Gateway Timeout: GET /orders",
        ],
        "recent_deploys": [
            {
                "sha": "a1b2c3d",
                "message": "feat: include order items in /orders response",
                "author": "dev@example.com",
                "timestamp": _ts(-3600),
                "diff_summary": "Removed selectinload(Order.items) from query, added manual item fetching loop",
            }
        ],
        "metrics": {
            "p99_latency_ms": 32000,
            "p50_latency_ms": 12000,
            "error_rate_percent": 45.2,
            "requests_per_minute": 120,
            "db_active_connections": 8,
            "db_pool_size": 8,
        },
    }


# ── Null Dereference ──────────────────────────────────────────────────

def _null_deref_alert() -> dict:
    return {
        "incident_id": "INC-2025-002",
        "service": "breakomatic",
        "severity": "P2",
        "timestamp": _ts(30),
        "title": "GET /users/{id} returning 500 for specific user IDs",
        "stack_trace": (
            "Traceback (most recent call last):\n"
            '  File "/app/breakomatic/app.py", line 72, in get_user\n'
            "    profile_text = user.profile_bio.upper()\n"
            "AttributeError: 'NoneType' object has no attribute 'upper'\n"
            "\n"
            "During handling of the above exception, another exception occurred:\n"
            "\n"
            "Traceback (most recent call last):\n"
            '  File "/app/.venv/lib/python3.11/site-packages/starlette/routing.py", line 69, in app\n'
            "    response = await func(request)\n"
            '  File "/app/.venv/lib/python3.11/site-packages/fastapi/routing.py", line 274, in app\n'
            "    raw_response = await run_endpoint_function(...)\n"
            "fastapi.exceptions.HTTPException: 500 Internal Server Error"
        ),
        "logs": [
            f"{_ts(0)} [INFO] GET /users/1 - 200 OK (12ms)",
            f"{_ts(5)} [INFO] GET /users/2 - 200 OK (8ms)",
            f"{_ts(10)} [INFO] GET /users/3 - request started",
            f"{_ts(10)} [ERROR] GET /users/3 - AttributeError: 'NoneType' object has no attribute 'upper'",
            f"{_ts(10)} [ERROR] 500 Internal Server Error: GET /users/3",
            f"{_ts(15)} [INFO] GET /users/4 - 200 OK (9ms)",
            f"{_ts(20)} [INFO] GET /users/5 - request started",
            f"{_ts(20)} [ERROR] GET /users/5 - AttributeError: 'NoneType' object has no attribute 'upper'",
            f"{_ts(20)} [ERROR] 500 Internal Server Error: GET /users/5",
            f"{_ts(25)} [WARN] Error rate for /users/{id} endpoint: 40% (2/5 requests failing)",
        ],
        "recent_deploys": [
            {
                "sha": "e4f5g6h",
                "message": "feat: add user profile summary to /users/{id} response",
                "author": "dev@example.com",
                "timestamp": _ts(-7200),
                "diff_summary": "Added profile_text = user.profile_bio.upper() without None check",
            }
        ],
        "metrics": {
            "p99_latency_ms": 45,
            "error_rate_percent": 40.0,
            "affected_user_ids": [3, 5],
            "requests_per_minute": 85,
        },
    }


# ── Bad Migration ────────────────────────────────────────────────────

def _bad_migration_alert() -> dict:
    return {
        "incident_id": "INC-2025-003",
        "service": "breakomatic",
        "severity": "P1",
        "timestamp": _ts(15),
        "title": "All order-related endpoints returning 500 after migration deploy",
        "stack_trace": (
            "Traceback (most recent call last):\n"
            '  File "/app/breakomatic/app.py", line 89, in list_orders\n'
            '    orders = db.query(Order).options(selectinload(Order.items)).all()\n'
            '  File "/app/.venv/lib/python3.11/site-packages/sqlalchemy/engine/default.py", line 608, in execute\n'
            "    cursor.execute(statement, parameters)\n"
            "sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such column: orders.status\n"
            "[SQL: SELECT orders.id AS orders_id, orders.user_id AS orders_user_id, "
            "orders.total AS orders_total, orders.status AS orders_status, "
            "orders.created_at AS orders_created_at FROM orders]"
        ),
        "logs": [
            f"{_ts(-60)} [INFO] Migration 0042_remove_legacy_columns starting...",
            f"{_ts(-55)} [INFO] Migration 0042: ALTER TABLE orders DROP COLUMN status",
            f"{_ts(-50)} [INFO] Migration 0042 completed successfully",
            f"{_ts(-45)} [INFO] Service restarting after migration...",
            f"{_ts(0)} [INFO] GET /orders - request started",
            f"{_ts(0)} [ERROR] OperationalError: no such column: orders.status",
            f"{_ts(0)} [ERROR] 500 Internal Server Error: GET /orders",
            f"{_ts(5)} [INFO] GET /users/1 - request started",
            f"{_ts(5)} [ERROR] OperationalError: no such column: orders.status",
            f"{_ts(5)} [ERROR] 500 Internal Server Error: GET /users/1",
            f"{_ts(10)} [INFO] GET /health - 200 OK",
            f"{_ts(15)} [CRIT] All order-related endpoints are failing. Health check passes but service is broken.",
        ],
        "recent_deploys": [
            {
                "sha": "i7j8k9l",
                "message": "chore: run migration 0042 - remove legacy columns",
                "author": "dba@example.com",
                "timestamp": _ts(-60),
                "diff_summary": "Migration drops 'status' column from orders table, but app code still references it",
            }
        ],
        "metrics": {
            "p99_latency_ms": 12,
            "error_rate_percent": 100.0,
            "healthy_endpoints": ["/health"],
            "broken_endpoints": ["/orders", "/users/{id}"],
        },
    }


# ── Leaked Connection ─────────────────────────────────────────────────

def _leaked_connection_alert() -> dict:
    return {
        "incident_id": "INC-2025-004",
        "service": "breakomatic",
        "severity": "P1",
        "timestamp": _ts(180),
        "title": "Service degradation — requests hanging after ~8 successful calls",
        "stack_trace": (
            "Traceback (most recent call last):\n"
            '  File "/app/breakomatic/app.py", line 35, in get_db\n'
            "    db = _SessionLocal()\n"
            '  File "/app/.venv/lib/python3.11/site-packages/sqlalchemy/orm/session.py", line 4782, in __init__\n'
            "    self._autobegin()\n"
            '  File "/app/.venv/lib/python3.11/site-packages/sqlalchemy/pool/impl.py", line 145, in connect\n'
            "    return _ConnectionFairy._checkout(pool)\n"
            "sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 3 reached, "
            "connection timed out, timeout 5.00 (Background on this error at: "
            "https://sqlalche.me/e/20/3o7r)"
        ),
        "logs": [
            f"{_ts(0)} [INFO] GET /users - 200 OK (15ms)",
            f"{_ts(10)} [INFO] GET /orders - 200 OK (45ms)",
            f"{_ts(20)} [INFO] GET /users - 200 OK (12ms)",
            f"{_ts(30)} [INFO] GET /health - 200 OK (2ms)",
            f"{_ts(40)} [INFO] GET /orders - 200 OK (38ms)",
            f"{_ts(50)} [INFO] GET /users/1 - 200 OK (18ms)",
            f"{_ts(60)} [INFO] GET /users/2 - 200 OK (14ms)",
            f"{_ts(70)} [INFO] GET /orders - 200 OK (42ms)",
            f"{_ts(80)} [WARN] GET /users - request started (waiting for connection...)",
            f"{_ts(85)} [ERROR] QueuePool limit reached: 8/8 connections checked out, 0 available",
            f"{_ts(85)} [ERROR] TimeoutError after 5.0s waiting for connection",
            f"{_ts(85)} [ERROR] 500 Internal Server Error: GET /users",
            f"{_ts(90)} [ERROR] All subsequent requests failing with pool timeout",
            f"{_ts(180)} [CRIT] Service effectively down — no connections available in pool",
        ],
        "recent_deploys": [
            {
                "sha": "m0n1o2p",
                "message": "refactor: simplify database session management",
                "author": "dev@example.com",
                "timestamp": _ts(-1800),
                "diff_summary": "Removed db.close() from get_db() dependency — sessions no longer returned to pool",
            }
        ],
        "metrics": {
            "p99_latency_ms": 5200,
            "error_rate_percent": 100.0,
            "db_active_connections": 8,
            "db_pool_size": 8,
            "db_pool_available": 0,
            "requests_succeeded_before_failure": 8,
        },
    }


# ── Broken Env ────────────────────────────────────────────────────────

def _broken_env_alert() -> dict:
    return {
        "incident_id": "INC-2025-005",
        "service": "breakomatic",
        "severity": "P0",
        "timestamp": _ts(0),
        "title": "Service failed to start — crash on boot after deploy",
        "stack_trace": (
            "Traceback (most recent call last):\n"
            '  File "/app/.venv/bin/uvicorn", line 8, in <module>\n'
            "    sys.exit(main())\n"
            '  File "/app/.venv/lib/python3.11/site-packages/uvicorn/main.py", line 577, in main\n'
            "    server.run()\n"
            '  File "/app/breakomatic/app.py", line 152, in <module>\n'
            "    app = create_app()\n"
            '  File "/app/breakomatic/app.py", line 68, in create_app\n'
            "    inject_startup()  # raises RuntimeError\n"
            '  File "/app/breakomatic/bugs/broken_env.py", line 42, in inject_startup\n'
            "    raise RuntimeError(\n"
            "RuntimeError: FATAL: Cannot initialize database.\n"
            "DATABASE_URL is set to 'sqlite:////dev/null/impossible.db' which is not a valid path.\n"
            "This appears to be a misconfiguration from the last deploy.\n"
            "The service cannot start until DATABASE_URL is corrected."
        ),
        "logs": [
            f"{_ts(-120)} [INFO] Deploy started: sha=q3r4s5t",
            f"{_ts(-60)} [INFO] Container image built successfully",
            f"{_ts(-30)} [INFO] Starting service with new configuration...",
            f"{_ts(-5)} [INFO] uvicorn starting on 0.0.0.0:8099",
            f"{_ts(0)} [FATAL] RuntimeError: FATAL: Cannot initialize database.",
            f"{_ts(0)} [FATAL] DATABASE_URL='sqlite:////dev/null/impossible.db'",
            f"{_ts(0)} [FATAL] Service exited with code 1",
            f"{_ts(1)} [INFO] Container restart attempt 1/5...",
            f"{_ts(6)} [FATAL] Service exited with code 1 (same error)",
            f"{_ts(7)} [CRIT] CrashLoopBackOff — service cannot start",
        ],
        "recent_deploys": [
            {
                "sha": "q3r4s5t",
                "message": "chore: update env config for new database cluster",
                "author": "ops@example.com",
                "timestamp": _ts(-120),
                "diff_summary": "Changed DATABASE_URL to point to new cluster, but used wrong path format",
            }
        ],
        "metrics": {
            "error_rate_percent": 100.0,
            "service_uptime_seconds": 0,
            "restart_attempts": 5,
            "last_healthy_deploy_sha": "prev123",
        },
    }
