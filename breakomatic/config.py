"""
Active bug state management.
Persists which bug is currently injected via a small JSON state file.
"""
from __future__ import annotations

import json
from pathlib import Path

STATE_FILE = Path(__file__).parent / ".active_bug.json"


def get_active_bug() -> str | None:
    """Read the currently active bug from the state file."""
    if not STATE_FILE.exists():
        return None
    try:
        data = json.loads(STATE_FILE.read_text())
        return data.get("active_bug")
    except (json.JSONDecodeError, OSError):
        return None


def set_active_bug(bug_name: str | None) -> None:
    """Write the active bug to the state file. Pass None to clear."""
    if bug_name is None:
        STATE_FILE.unlink(missing_ok=True)
    else:
        STATE_FILE.write_text(json.dumps({"active_bug": bug_name}, indent=2) + "\n")


def clear_active_bug() -> None:
    """Remove any active bug."""
    set_active_bug(None)
