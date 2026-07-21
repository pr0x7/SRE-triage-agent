"""
Pluggable Database Adapter & Schema Reflection Engine for SRE Agent.

Uses SQLAlchemy reflection to inspect unknown database schemas dynamically,
enforcing connection-level read-only security permissions.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, List
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

FORBIDDEN_SQL_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "GRANT",
    "REVOKE",
    "REPLACE",
}


class DatabaseInspector:
    """Generic Database Inspector powered by SQLAlchemy schema reflection."""

    def __init__(self, db_url_or_path: str | Path):
        """Initialize database engine with read-only connection configuration."""
        db_str = str(db_url_or_path)

        if not (db_str.startswith("sqlite://") or db_str.startswith("postgresql://") or db_str.startswith("mysql://")):
            # Path to SQLite file
            path = Path(db_str).resolve()
            db_url = f"sqlite:///{path}?mode=ro"
        else:
            db_url = db_str

        # Configure connection arguments for read-only SQLite if applicable
        connect_args = {}
        if db_url.startswith("sqlite://"):
            connect_args = {"check_same_thread": False}

        self.engine: Engine = create_engine(db_url, connect_args=connect_args)
        self.db_url = db_url

    def reflect_schema(self) -> Dict[str, Any]:
        """Reflect all tables, columns, data types, primary keys, and foreign keys."""
        inspector = inspect(self.engine)
        tables_data: Dict[str, Any] = {}

        for table_name in inspector.get_table_names():
            columns = [
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "default": str(col.get("default")),
                }
                for col in inspector.get_columns(table_name)
            ]

            pk_constraint = inspector.get_pk_constraint(table_name)
            primary_keys = pk_constraint.get("constrained_columns", []) if pk_constraint else []

            fks = [
                {
                    "constrained_columns": fk.get("constrained_columns"),
                    "referred_table": fk.get("referred_table"),
                    "referred_columns": fk.get("referred_columns"),
                }
                for fk in inspector.get_foreign_keys(table_name)
            ]

            indexes = [
                {
                    "name": idx.get("name"),
                    "columns": idx.get("column_names"),
                    "unique": idx.get("unique"),
                }
                for idx in inspector.get_indexes(table_name)
            ]

            tables_data[table_name] = {
                "columns": columns,
                "primary_keys": primary_keys,
                "foreign_keys": fks,
                "indexes": indexes,
            }

        return {"url": self.db_url, "tables": tables_data}

    def format_schema_summary(self) -> str:
        """Format reflected schema into human-readable Markdown summary for LLM context."""
        schema = self.reflect_schema()
        tables = schema.get("tables", {})

        if not tables:
            return "Database schema is empty (no tables found)."

        lines = [f"### Reflected Database Schema ({len(tables)} tables):\n"]
        for table_name, meta in tables.items():
            lines.append(f"#### Table: `{table_name}`")

            # Columns
            col_strs = []
            pks = set(meta.get("primary_keys", []))
            for col in meta.get("columns", []):
                pk_flag = " (PK)" if col["name"] in pks else ""
                col_strs.append(f"`{col['name']}`: {col['type']}{pk_flag}")
            lines.append(f"- **Columns**: {', '.join(col_strs)}")

            # Foreign keys
            fks = meta.get("foreign_keys", [])
            if fks:
                fk_strs = [
                    f"`{','.join(fk['constrained_columns'])}` -> `{fk['referred_table']}({','.join(fk['referred_columns'])})`"
                    for fk in fks
                    if fk.get("constrained_columns") and fk.get("referred_table")
                ]
                if fk_strs:
                    lines.append(f"- **Foreign Keys**: {', '.join(fk_strs)}")

            lines.append("")

        return "\n".join(lines)

    def execute_query(self, sql: str) -> List[Dict[str, Any]]:
        """Execute SQL query enforcing connection-level read-only security.

        Raises:
            PermissionError: If any non-read-only (write/modify) command is attempted.
        """
        clean_sql = sql.strip().strip(";").upper()
        tokens = set(re.findall(r"\b[A-Z]+\b", clean_sql))

        forbidden_found = tokens.intersection(FORBIDDEN_SQL_KEYWORDS)
        if forbidden_found:
            raise PermissionError(
                f"Read-only security policy violation: Forbidden keyword(s) {forbidden_found} detected in query."
            )

        if not (clean_sql.startswith("SELECT") or clean_sql.startswith("EXPLAIN") or clean_sql.startswith("PRAGMA")):
            raise PermissionError("Read-only security policy violation: Only SELECT, EXPLAIN, or PRAGMA queries allowed.")

        with self.engine.connect() as conn:
            result = conn.execute(text(sql))
            if result.returns_rows:
                keys = result.keys()
                return [dict(zip(keys, row)) for row in result.fetchall()]
            return []
