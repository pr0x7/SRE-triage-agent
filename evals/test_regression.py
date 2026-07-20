"""
Regression test suite for break-o-matic endpoints.
These tests verify core functionality and are run inside the sandbox.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from breakomatic.app import create_app

# Build the FastAPI client
# Note: create_app() uses get_active_bug() to inject bugs if set,
# so this client will execute the active bug in tests!
client = TestClient(create_app())


def test_n_plus_one() -> None:
    """
    Regression test for 'n_plus_one' bug.
    """
    response = client.get("/orders")
    assert response.status_code == 200
    orders = response.json()
    assert len(orders) > 0
    # Check that eager/lazy loading of items is present and formatted
    first_order = orders[0]
    assert "items" in first_order
    assert isinstance(first_order["items"], list)


def test_null_deref() -> None:
    """
    Regression test for 'null_deref' bug.
    """
    response = client.get("/users/3")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Charlie Brown"
    assert data["profile_summary"] == "No bio provided"


def test_bad_migration() -> None:
    """
    Regression test for 'bad_migration' bug.
    """
    response = client.get("/orders")
    assert response.status_code == 200
    orders = response.json()
    assert len(orders) > 0
    # Check that status column is present
    first_order = orders[0]
    assert "status" in first_order


def test_leaked_connection() -> None:
    """
    Regression test for 'leaked_connection' bug.
    """
    for _ in range(10):
        response = client.get("/orders")
        assert response.status_code == 200


def test_broken_env() -> None:
    """
    Regression test for 'broken_env' bug.
    """
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"