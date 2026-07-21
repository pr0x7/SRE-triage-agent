"""
Unit tests for Phase 21 Per-Repo Persistent Memory.
"""
import json
import sqlite3
from pathlib import Path
import pytest
from langgraph.store.sqlite import SqliteStore

from agent.memory import save_to_memory, search_memory


@pytest.fixture
def memory_store(tmp_path):
    """Fixture providing a fresh isolated SQLite store for memory testing."""
    db_file = tmp_path / "test_store.db"
    store_conn = sqlite3.connect(str(db_file), check_same_thread=False, isolation_level=None)
    store = SqliteStore(store_conn)
    store.setup()
    return store


def test_save_and_search_repo_scoped_memory(memory_store):
    """Verify saving and searching incident memory scoped to a specific repository."""
    diagnosis = {
        "summary": "KeyError missing currency in payment processing.",
        "root_cause": "KeyError: 'currency'",
        "evidence": "File app.py line 12",
        "suggested_fix": "data.get('currency', 'USD')",
        "severity": "P1",
    }

    save_to_memory(
        bug_name="missing_currency_key",
        diagnosis_json=json.dumps(diagnosis),
        store=memory_store,
        repo_name="payment-api",
    )

    # Search for memory within the payment-api namespace
    match = search_memory(
        incident_context="KeyError: 'currency' in app.py process_payment",
        store=memory_store,
        repo_name="payment-api",
    )
    assert match == "missing_currency_key"


def test_memory_isolation_between_repos(memory_store):
    """Verify that memory saved under repository A does NOT leak or match for repository B."""
    diagnosis = {
        "summary": "KeyError missing currency in payment processing.",
        "root_cause": "KeyError: 'currency'",
        "evidence": "File app.py line 12",
        "suggested_fix": "data.get('currency', 'USD')",
        "severity": "P1",
    }

    # Save memory exclusively under payment-api namespace
    save_to_memory(
        bug_name="missing_currency_key",
        diagnosis_json=json.dumps(diagnosis),
        store=memory_store,
        repo_name="payment-api",
    )

    # Search for identical error under user-auth-service namespace
    match_auth = search_memory(
        incident_context="KeyError: 'currency' in process_payment",
        store=memory_store,
        repo_name="user-auth-service",
    )
    # Must be None — no memory leakage between distinct repositories!
    assert match_auth is None


def test_store_namespace_structure(memory_store):
    """Verify the underlying LangGraph Store namespace tuple structure ("incidents", repo_name)."""
    save_to_memory(
        bug_name="null_deref",
        diagnosis_json=json.dumps({"root_cause": "null_deref"}),
        store=memory_store,
        repo_name="user-auth-service",
    )

    # Directly search store namespace tuple ("incidents", "user-auth-service")
    items = memory_store.search(("incidents", "user-auth-service"))
    assert len(items) == 1
    assert items[0].key == "null_deref"
    assert items[0].value["repo_name"] == "user-auth-service"

    # Search empty namespace for another repo
    items_other = memory_store.search(("incidents", "other-service"))
    assert len(items_other) == 0
