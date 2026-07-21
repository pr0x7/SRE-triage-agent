"""
Empirical Unit & Safety Verification Tests (Phase 19/20 Verification).
"""
import time
import docker
import pytest
from agent.security import ScopedCredentialManager
from agent.db_adapter import DatabaseInspector
from agent.docker_sandbox import DockerSandbox


def test_network_mode_none_blocks_outbound_calls():
    """Empirically verify that network_mode='none' blocks outbound network egress inside sandbox."""
    try:
        sandbox = DockerSandbox(network_mode="none")
        sandbox.start()
        res = sandbox.execute("python -c \"import urllib.request; urllib.request.urlopen('https://8.8.8.8', timeout=2)\"")
        assert res.exit_code != 0
        assert "URLError" in res.output or "Network is unreachable" in res.output or "timed out" in res.output or "Name or service not known" in res.output
    finally:
        sandbox.stop()


def test_zero_leaked_containers():
    """Empirically verify that 10 sequential sandbox executions leave zero leaked containers."""
    client = docker.from_env()

    # Initial container names
    initial_names = set(c.name for c in client.containers.list(all=True) if c.name.startswith("deepagents-sandbox-"))

    created_names = []
    for _ in range(10):
        sb = DockerSandbox(network_mode="none")
        sb.start()
        if sb._container:
            created_names.append(sb._container.name)
        sb.execute("echo 'test'")
        sb.stop()

    time.sleep(0.5)  # Allow Docker daemon split-second to finish removing container state

    # Query active containers
    all_containers = client.containers.list(all=True)
    leaked = [c for c in all_containers if c.name in created_names]
    assert len(leaked) == 0, f"Found {len(leaked)} leaked containers from test run: {[c.name for c in leaked]}"


def test_token_ttl_expiration():
    """Empirically verify that short-lived credentials expire past their TTL."""
    mgr = ScopedCredentialManager(default_ttl_seconds=1)
    token = mgr.issue_token(scope="sandbox:execute", ttl_seconds=1)

    assert mgr.validate_token(token.token_id, required_scope="sandbox:execute") is True

    # Sleep past 1s TTL
    time.sleep(1.2)

    assert mgr.validate_token(token.token_id, required_scope="sandbox:execute") is False


def test_readonly_sql_execution_rejection(tmp_path):
    """Empirically verify that connection-level read-only DatabaseInspector rejects modify queries."""
    db_file = tmp_path / "test_sec.db"
    inspector = DatabaseInspector(db_file)

    # Initial table setup via direct connection
    with inspector.engine.connect() as conn:
        conn.exec_driver_sql("CREATE TABLE users (id INT, name TEXT)")
        conn.exec_driver_sql("INSERT INTO users VALUES (1, 'Alice')")
        conn.commit()

    # Valid SELECT query
    rows = inspector.execute_query("SELECT * FROM users")
    assert len(rows) == 1

    # Attempt forbidden write queries
    forbidden_queries = [
        "INSERT INTO users VALUES (2, 'Bob')",
        "UPDATE users SET name = 'Hacked' WHERE id = 1",
        "DELETE FROM users WHERE id = 1",
        "DROP TABLE users",
        "ALTER TABLE users ADD COLUMN pass TEXT",
    ]

    for q in forbidden_queries:
        with pytest.raises(PermissionError) as exc:
            inspector.execute_query(q)
        assert "Read-only security policy violation" in str(exc.value)
