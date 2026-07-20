"""
Bug registry — maps bug names to their modules.

Each bug module must export:
    NAME: str           — canonical bug name
    DESCRIPTION: str    — what the bug does
    EXPECTED_FIX: str   — the known correct fix (for eval)
    inject(app, engine, get_db) -> None  — patches the app to exhibit the bug
"""
from __future__ import annotations

import importlib
from types import ModuleType

# Canonical bug names → module paths
BUG_REGISTRY: dict[str, str] = {
    "n_plus_one": "breakomatic.bugs.n_plus_one",
    "null_deref": "breakomatic.bugs.null_deref",
    "bad_migration": "breakomatic.bugs.bad_migration",
    "leaked_connection": "breakomatic.bugs.leaked_connection",
    "broken_env": "breakomatic.bugs.broken_env",
}


def get_bug_module(name: str) -> ModuleType:
    """Import and return a bug module by name."""
    if name not in BUG_REGISTRY:
        available = ", ".join(sorted(BUG_REGISTRY))
        raise ValueError(f"Unknown bug: {name!r}. Available: {available}")
    return importlib.import_module(BUG_REGISTRY[name])


def list_bugs() -> list[dict[str, str]]:
    """Return metadata for all registered bugs."""
    result = []
    for name in sorted(BUG_REGISTRY):
        mod = get_bug_module(name)
        result.append({
            "name": getattr(mod, "NAME", name),
            "description": getattr(mod, "DESCRIPTION", ""),
            "expected_fix": getattr(mod, "EXPECTED_FIX", ""),
        })
    return result
