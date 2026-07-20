"""
Basic test suite for break-o-matic endpoints.
These tests verify core functionality and are run inside the sandbox.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from breakomatic.app import create_app

# Build the FastAPI client
# Note: create_app() uses get_active_bug() to inject bugs if set,
# so this client will execute the active bug in tests!
client = TestClient(create_app())


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_list_users() -> None:
    response = client.get("/users")
    assert response.status_code == 200
    users = response.json()
    assert len(users) >= 3
    assert any(u["name"] == "Alice Johnson" for u in users)


def test_get_user_success() -> None:
    # User 1 has bio and profile summary
    response = client.get("/users/1")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Alice Johnson"
    assert "profile_summary" in data


def test_get_user_no_bio_success() -> None:
    # User 3 (Charlie) has no bio (NULL/None)
    # The null_deref bug crashes on this user, but in clean mode it must pass!
    response = client.get("/users/3")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Charlie Brown"
    assert data["profile_summary"] == "No bio provided"


def test_list_orders() -> None:
    response = client.get("/orders")
    assert response.status_code == 200
    orders = response.json()
    assert len(orders) > 0
    # Check that eager/lazy loading of items is present and formatted
    first_order = orders[0]
    assert "items" in first_order
    assert isinstance(first_order["items"], list)


def test_create_order() -> None:
    payload = {
        "user_id": 1,
        "items": [
            {"product_name": "Widget A", "quantity": 2, "price": 9.99}
        ]
    }
    response = client.post("/orders?user_id=1", json=[{"product_name": "Widget A", "quantity": 2, "price": 9.99}])
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["total"] == 19.98
