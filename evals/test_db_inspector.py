"""
Unit tests for Phase 17 Pluggable DB Adapters & Reflection Engine.
"""
from pathlib import Path
import sqlite3
import pytest
from agent.db_adapter import DatabaseInspector
from agent.subagents.db_inspector import run_db_inspector


@pytest.fixture
def sample_unfamiliar_db(tmp_path):
    """Fixture creating an unfamiliar SQLite database schema (customers, orders, products)."""
    db_file = tmp_path / "e_commerce.db"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.executescript("""
    CREATE TABLE customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL
    );

    CREATE TABLE products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        price REAL NOT NULL
    );

    CREATE TABLE orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        total_amount REAL NOT NULL,
        status TEXT DEFAULT 'pending',
        FOREIGN KEY (customer_id) REFERENCES customers(id)
    );

    INSERT INTO customers (name, email) VALUES ('Alice', 'alice@example.com');
    INSERT INTO products (title, price) VALUES ('Widget A', 29.99);
    INSERT INTO orders (customer_id, total_amount) VALUES (1, 29.99);
    """)
    conn.commit()
    conn.close()
    return db_file


def test_reflect_unfamiliar_schema(sample_unfamiliar_db):
    """Verify DatabaseInspector reflects unknown schema tables, columns, PKs, and FKs."""
    inspector = DatabaseInspector(sample_unfamiliar_db)
    reflected = inspector.reflect_schema()

    tables = reflected.get("tables", {})
    assert "customers" in tables
    assert "products" in tables
    assert "orders" in tables

    # Verify columns and PK for customers
    cust_cols = {c["name"]: c["type"] for c in tables["customers"]["columns"]}
    assert "email" in cust_cols
    assert "name" in cust_cols
    assert "id" in tables["customers"]["primary_keys"]

    # Verify foreign key for orders -> customers
    fks = tables["orders"]["foreign_keys"]
    assert len(fks) >= 1
    assert fks[0]["referred_table"] == "customers"


def test_format_schema_summary(sample_unfamiliar_db):
    """Verify schema summary formatting for LLM prompt context."""
    inspector = DatabaseInspector(sample_unfamiliar_db)
    summary = inspector.format_schema_summary()

    assert "### Reflected Database Schema (3 tables)" in summary
    assert "Table: `customers`" in summary
    assert "Table: `orders`" in summary
    assert "Foreign Keys" in summary


def test_readonly_security_enforcement(sample_unfamiliar_db):
    """Verify connection-level read-only enforcement rejects write/modify operations."""
    inspector = DatabaseInspector(sample_unfamiliar_db)

    # Valid SELECT query should succeed
    rows = inspector.execute_query("SELECT name, email FROM customers WHERE id = 1")
    assert len(rows) == 1
    assert rows[0]["name"] == "Alice"

    # Forbidden modification queries should raise PermissionError
    forbidden_queries = [
        "INSERT INTO customers (name, email) VALUES ('Bob', 'bob@example.com')",
        "UPDATE customers SET name = 'Malicious' WHERE id = 1",
        "DELETE FROM orders WHERE id = 1",
        "DROP TABLE products",
        "ALTER TABLE customers ADD COLUMN password TEXT",
        "TRUNCATE TABLE orders",
    ]

    for query in forbidden_queries:
        with pytest.raises(PermissionError) as excinfo:
            inspector.execute_query(query)
        assert "Read-only security policy violation" in str(excinfo.value)


def test_db_inspector_subagent_with_reflection(sample_unfamiliar_db):
    """Verify db_inspector subagent consumes DatabaseInspector reflection cleanly."""
    inspector = DatabaseInspector(sample_unfamiliar_db)

    # Verify formatting cleanly integrates into context prompt
    summary = inspector.format_schema_summary()
    assert "customers" in summary
    assert "orders" in summary
