"""
Change detector — compares the current schema state against a saved snapshot.

A snapshot records, for every table:
  - column names and types
  - current row count

On the next run, if a table has new/removed columns, a changed row count,
or is new/deleted entirely, it is flagged for re-indexing.

Snapshots are stored as a lightweight SQLite file (theia_snapshot.db)
in the project root — separate from the data databases.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from catalog.metadata_extractor import extract_table
from connectors.sqlite_connector import list_schemas, list_tables
from config.settings import settings

_SNAPSHOT_PATH = settings.data_dir.parent / "theia_snapshot.db"


def _get_snapshot_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_SNAPSHOT_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            schema_name TEXT NOT NULL,
            table_name  TEXT NOT NULL,
            columns_json TEXT NOT NULL,
            row_count   INTEGER NOT NULL,
            indexed_at  TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (schema_name, table_name)
        )
    """)
    conn.commit()
    return conn


@dataclass
class TableChange:
    schema: str
    table: str
    reason: str          # "new", "deleted", "columns_changed", "row_count_changed"
    old_row_count: int = 0
    new_row_count: int = 0


def _current_state() -> dict[str, dict]:
    """Return {'{schema}.{table}': {columns, row_count}} for all tables."""
    state = {}
    for schema in list_schemas():
        for table in list_tables(schema):
            try:
                meta = extract_table(schema, table)
                cols = {c.name: c.type for c in meta.columns}
                state[f"{schema}.{table}"] = {
                    "columns": cols,
                    "row_count": meta.row_count,
                }
            except Exception:
                pass
    return state


def save_snapshot() -> int:
    """Save the current schema state as the new baseline. Returns table count."""
    state = _current_state()
    conn = _get_snapshot_conn()
    try:
        for key, info in state.items():
            schema, table = key.split(".", 1)
            conn.execute(
                """INSERT OR REPLACE INTO snapshots
                   (schema_name, table_name, columns_json, row_count)
                   VALUES (?, ?, ?, ?)""",
                (schema, table, json.dumps(info["columns"]), info["row_count"]),
            )
        conn.commit()
        return len(state)
    finally:
        conn.close()


def detect_changes() -> list[TableChange]:
    """
    Compare current state against the last snapshot.
    Returns a list of TableChange objects for tables that need re-indexing.
    """
    current = _current_state()
    conn = _get_snapshot_conn()
    changes: list[TableChange] = []

    try:
        rows = conn.execute(
            "SELECT schema_name, table_name, columns_json, row_count FROM snapshots"
        ).fetchall()
        snapshot = {
            f"{r[0]}.{r[1]}": {"columns": json.loads(r[2]), "row_count": r[3]}
            for r in rows
        }
    finally:
        conn.close()

    # Check for new or changed tables
    for key, info in current.items():
        schema, table = key.split(".", 1)
        if key not in snapshot:
            changes.append(TableChange(schema, table, "new", new_row_count=info["row_count"]))
        else:
            prev = snapshot[key]
            if info["columns"] != prev["columns"]:
                changes.append(TableChange(schema, table, "columns_changed",
                                           old_row_count=prev["row_count"],
                                           new_row_count=info["row_count"]))
            elif abs(info["row_count"] - prev["row_count"]) > max(1, prev["row_count"] * 0.05):
                # Row count changed by more than 5% (or at least 1 row)
                changes.append(TableChange(schema, table, "row_count_changed",
                                           old_row_count=prev["row_count"],
                                           new_row_count=info["row_count"]))

    # Check for deleted tables
    for key in snapshot:
        if key not in current:
            schema, table = key.split(".", 1)
            changes.append(TableChange(schema, table, "deleted"))

    return changes


if __name__ == "__main__":
    print("Saving snapshot…")
    n = save_snapshot()
    print(f"Snapshot saved for {n} tables.")
    print("\nDetecting changes…")
    changes = detect_changes()
    if changes:
        for c in changes:
            print(f"  {c.schema}.{c.table}: {c.reason}")
    else:
        print("  No changes detected.")
