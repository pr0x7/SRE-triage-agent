"""
Bug: Leaked DB Connections
──────────────────────────
Overrides the get_db dependency so sessions are opened but never closed.
With a pool of 5+3=8 connections, the pool exhausts after 8 requests,
and the 9th request hangs until pool_timeout (5s), then crashes.

Symptom:  First ~8 requests succeed normally. Request 9+ hangs 5s then:
          sqlalchemy.exc.TimeoutError: QueuePool limit reached
Fix:      Ensure db.close() is called in a finally block (restore proper get_db).
"""
from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy.orm import Session

NAME = "leaked_connection"
DESCRIPTION = (
    "The get_db() dependency opens a SQLAlchemy session but never calls "
    "db.close(). Each request leaks one connection from the pool. After "
    "~8 requests (pool_size=5 + max_overflow=3), the pool is exhausted "
    "and subsequent requests fail with TimeoutError after 5 seconds."
)
EXPECTED_FIX = (
    "Add db.close() in a finally block in the get_db() dependency, or use "
    "a try/yield/finally pattern to ensure sessions are always returned to the pool."
)

# Track leaked sessions for debugging/cleanup
_leaked_sessions: list[Session] = []


def inject(app: FastAPI, engine, get_db) -> None:
    """Override get_db with a version that never closes the session."""

    def leaky_get_db():
        from breakomatic.app import _SessionLocal
        db = _SessionLocal()
        _leaked_sessions.append(db)
        yield db
        # BUG: deliberately NOT closing the session.
        # Normal code would have:
        #   finally:
        #       db.close()

    app.dependency_overrides[get_db] = leaky_get_db
