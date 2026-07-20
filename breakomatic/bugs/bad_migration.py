"""
Bug: Bad Migration (missing column)
────────────────────────────────────
Executes ALTER TABLE orders DROP COLUMN status — simulating a broken
migration that accidentally removed a column the app still queries.

Symptom:  Any endpoint that touches orders.status returns a 500
          (sqlalchemy.exc.OperationalError: no such column: orders.status)
Fix:      Add the column back: ALTER TABLE orders ADD COLUMN status VARCHAR(20) DEFAULT 'pending'
"""
from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import text

NAME = "bad_migration"
DESCRIPTION = (
    "A bad database migration dropped the 'status' column from the orders table. "
    "Every query that references orders.status now fails with "
    "OperationalError: no such column: orders.status. Affects /orders and /users/{id}."
)
EXPECTED_FIX = (
    "Run: ALTER TABLE orders ADD COLUMN status VARCHAR(20) DEFAULT 'pending' "
    "to restore the missing column."
)


def inject(app: FastAPI, engine, get_db) -> None:
    """Drop the 'status' column from orders — simulates a botched migration."""
    with engine.connect() as conn:
        # Check if column exists before dropping (idempotent)
        result = conn.execute(text("PRAGMA table_info(orders)"))
        columns = [row[1] for row in result.fetchall()]
        if "status" in columns:
            conn.execute(text("ALTER TABLE orders DROP COLUMN status"))
            conn.commit()
