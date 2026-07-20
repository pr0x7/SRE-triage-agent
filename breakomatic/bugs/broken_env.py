"""
Bug: Broken Environment Variable
─────────────────────────────────
Simulates a deploy that corrupts a required environment variable.
The app crashes on boot — it never even starts serving requests.

Symptom:  uvicorn exits immediately with RuntimeError on startup.
Fix:      Set DATABASE_URL to a valid SQLite path (or remove the override
          so the default kicks in).
"""
from __future__ import annotations

import os

NAME = "broken_env"
DESCRIPTION = (
    "A bad deploy set DATABASE_URL to an invalid path "
    "('sqlite:///dev/null/impossible.db'). The app crashes during startup "
    "with RuntimeError before serving any requests."
)
EXPECTED_FIX = (
    "Fix the DATABASE_URL environment variable: either unset it (to use the "
    "default path) or set it to a valid SQLite path like "
    "'sqlite:///./breakomatic/breakomatic.db'."
)

# The broken value that will be injected
_BROKEN_DB_URL = "sqlite:////dev/null/impossible.db"


def inject_startup() -> None:
    """Called during create_app() BEFORE engine creation.
    Sets DATABASE_URL to garbage and raises RuntimeError.
    This is NOT the normal inject() — it's special because the service
    must crash on boot, not after route registration.
    """
    os.environ["DATABASE_URL"] = _BROKEN_DB_URL

    raise RuntimeError(
        f"FATAL: Cannot initialize database.\n"
        f"DATABASE_URL is set to '{_BROKEN_DB_URL}' which is not a valid path.\n"
        f"This appears to be a misconfiguration from the last deploy.\n"
        f"The service cannot start until DATABASE_URL is corrected."
    )


def inject(app, engine, get_db) -> None:
    """Not used — broken_env crashes during startup via inject_startup()."""
    raise RuntimeError("broken_env uses inject_startup(), not inject()")
