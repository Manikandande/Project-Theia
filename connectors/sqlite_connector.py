"""
Multi-schema SQLite connector.

Opens a single in-memory coordinator connection, then ATTACHes each database
under its schema alias (music, sales, rental, geography).  Every query runs
through this connection so cross-schema JOINs work seamlessly.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from config.settings import settings


_SCHEMAS: list[tuple[str, Path]] = [
    ("music",       settings.chinook_db),
    ("sales",       settings.northwind_db),
    ("rental",      settings.sakila_db),
    ("geography",   settings.world_db),
    ("healthcare",  settings.healthcare_db),
]


def _attach_all(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    for alias, path in _SCHEMAS:
        conn.execute(f"ATTACH DATABASE '{path}' AS {alias}")


def get_connection() -> sqlite3.Connection:
    """Return a new connection with all schemas attached. Caller owns the lifecycle."""
    conn = sqlite3.connect(":memory:")
    _attach_all(conn)
    return conn


@contextmanager
def managed_connection():
    """Context manager that automatically closes the connection."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def execute_query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """
    Run a read-only SELECT and return rows as a list of dicts.
    Raises ValueError if the statement is not a SELECT.
    """
    stripped = sql.strip().upper()
    if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
        raise ValueError("Only SELECT queries are permitted.")

    with managed_connection() as conn:
        cursor = conn.execute(sql, params)
        columns = [d[0] for d in cursor.description]
        rows = cursor.fetchmany(settings.max_sql_rows)
        return [dict(zip(columns, row)) for row in rows]


def list_schemas() -> list[str]:
    """Return the names of all attached schemas."""
    return [alias for alias, _ in _SCHEMAS]


_INTERNAL_TABLES = {"sqlite_sequence", "sqlite_stat1", "sqlite_stat2", "sqlite_stat3", "sqlite_stat4"}


def list_tables(schema: str) -> list[str]:
    """Return table names (not views, not SQLite internals) for a given schema alias."""
    with managed_connection() as conn:
        rows = conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows if r[0] not in _INTERNAL_TABLES]


def table_exists(schema: str, table: str) -> bool:
    with managed_connection() as conn:
        row = conn.execute(
            f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None
