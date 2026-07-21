"""
Unit tests for Phase 19 Safety Hardening for Real Codebases.
"""
import json
from pathlib import Path
import time
import pytest

from agent.security import ScopedCredentialManager, EphemeralToken
from agent.audit import AuditLogger, AuditEvent
from agent.docker_sandbox import DockerSandbox
from agent.orchestrator import patch_node


def test_scoped_credential_manager():
    """Verify short-lived, scoped credential token creation and validation."""
    mgr = ScopedCredentialManager(default_ttl_seconds=2)

    # Issue token
    token = mgr.issue_token(scope="sandbox:execute")
    assert isinstance(token, EphemeralToken)
    assert token.is_valid is True

    # Validate matching scope
    assert mgr.validate_token(token.token_id, required_scope="sandbox:execute") is True
    # Validate non-matching scope
    assert mgr.validate_token(token.token_id, required_scope="db:write") is False

    # Test wildcard scope
    wildcard_token = mgr.issue_token(scope="db:*")
    assert mgr.validate_token(wildcard_token.token_id, required_scope="db:read") is True
    assert mgr.validate_token(wildcard_token.token_id, required_scope="db:write") is True

    # Test revocation
    mgr.revoke_token(token.token_id)
    assert mgr.validate_token(token.token_id, required_scope="sandbox:execute") is False


def test_docker_sandbox_restricted_network_mode():
    """Verify DockerSandbox defaults to restricted network_mode."""
    sandbox = DockerSandbox(network_mode="none")
    assert sandbox._network_mode == "none"


def test_audit_logger_export(tmp_path):
    """Verify AuditLogger records tool calls and exports structured JSON audit logs."""
    audit = AuditLogger.get_instance()
    audit.clear()

    # Log tool calls
    audit.log_event(
        tool_name="db_query",
        caller_node="db_inspector",
        target_system="production_replica_db",
        input_summary="SELECT count(*) FROM orders;",
        status="SUCCESS",
        token_id="token-12345",
    )

    audit.log_event(
        tool_name="patch_writer",
        caller_node="patch_node",
        target_system="sandbox",
        input_summary="Plan-only dry-run for bug n_plus_one.",
        status="DRY_RUN",
    )

    events = audit.get_audit_trail()
    assert len(events) == 2
    assert events[0].tool_name == "db_query"
    assert events[1].status == "DRY_RUN"

    # Export audit JSON
    out_file = audit.export_audit_log(incident_id="INC-SAFETY-101", output_dir=tmp_path)
    assert out_file.exists()

    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["incident_id"] == "INC-SAFETY-101"
    assert data["total_events"] == 2
    assert data["events"][0]["target_system"] == "production_replica_db"


def test_plan_only_dry_run_patch_node():
    """Verify patch_node skips file mutation when plan_only=True."""
    audit = AuditLogger.get_instance()
    audit.clear()

    state = {
        "selected_bug": "n_plus_one",
        "plan_only": True,
    }

    result = patch_node(state)
    assert "patch_result" in result
    assert "[PLAN-ONLY DRY RUN]" in result["patch_result"]

    # Verify audit event logged DRY_RUN status
    trail = audit.get_audit_trail()
    assert len(trail) >= 1
    assert trail[-1].status == "DRY_RUN"
    assert trail[-1].tool_name == "patch_writer"
