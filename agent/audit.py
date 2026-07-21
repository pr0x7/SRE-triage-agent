"""
Audit Logging Module for SRE Agent.

Tracks and records every tool invocation, action against sandbox/production systems,
and credential verification event into structured JSON audit trails.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class AuditEvent:
    """Record of a single agent action or tool invocation."""

    event_id: str
    timestamp: str
    tool_name: str
    caller_node: str
    target_system: str
    input_summary: str
    status: str
    token_id: Optional[str] = None


class AuditLogger:
    """Singleton audit logger capturing actions taken across real and sandbox systems."""

    _instance: Optional[AuditLogger] = None

    def __init__(self):
        self._events: List[AuditEvent] = []

    @classmethod
    def get_instance(cls) -> AuditLogger:
        if cls._instance is None:
            cls._instance = AuditLogger()
        return cls._instance

    def log_event(
        self,
        tool_name: str,
        caller_node: str,
        target_system: str,
        input_summary: str,
        status: str = "SUCCESS",
        token_id: Optional[str] = None,
    ) -> AuditEvent:
        """Log a new tool invocation or system access event."""
        event = AuditEvent(
            event_id=f"audit-{uuid.uuid4().hex[:10]}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool_name=tool_name,
            caller_node=caller_node,
            target_system=target_system,
            input_summary=input_summary[:300],  # Cap summary length
            status=status,
            token_id=token_id,
        )
        self._events.append(event)
        return event

    def get_audit_trail(self) -> List[AuditEvent]:
        """Return full chronological audit trail."""
        return list(self._events)

    def clear(self) -> None:
        """Clear recorded events (useful between test runs)."""
        self._events.clear()

    def export_audit_log(self, incident_id: str, output_dir: str | Path = ".") -> Path:
        """Export audit events into a structured audit_<incident_id>.json file.

        Returns:
            Path: Path to exported audit JSON file.
        """
        out_path = Path(output_dir) / f"audit_{incident_id}.json"
        data = {
            "incident_id": incident_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "total_events": len(self._events),
            "events": [asdict(ev) for ev in self._events],
        }
        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return out_path
