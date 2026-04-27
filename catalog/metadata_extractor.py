"""
Metadata extractor — crawls every attached schema and returns a rich
catalog of tables, columns, types, keys, and sample data.

Each table entry is self-contained so it can be embedded independently.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from connectors.sqlite_connector import list_schemas, list_tables, managed_connection


@dataclass
class ColumnMeta:
    name: str
    type: str
    not_null: bool
    default_value: Any
    is_primary_key: bool
    is_foreign_key: bool = False
    references: str | None = None    # "other_table.other_column"


@dataclass
class TableMeta:
    schema: str
    table: str
    columns: list[ColumnMeta] = field(default_factory=list)
    row_count: int = 0
    sample_rows: list[dict] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.schema}.{self.table}"

    def as_text(self) -> str:
        """Plain-English description suitable for embedding."""
        col_lines = []
        for c in self.columns:
            flags = []
            if c.is_primary_key:
                flags.append("primary key")
            if c.is_foreign_key:
                flags.append(f"foreign key → {c.references}")
            if c.not_null:
                flags.append("required")
            flag_str = f" ({', '.join(flags)})" if flags else ""
            col_lines.append(f"  - {c.name} [{c.type}]{flag_str}")

        sample_str = ""
        if self.sample_rows:
            keys = list(self.sample_rows[0].keys())
            values = [str(list(r.values())) for r in self.sample_rows[:2]]
            sample_str = f"\nSample rows (columns: {keys}):\n" + "\n".join(values)

        return (
            f"Table: {self.full_name}\n"
            f"Rows: {self.row_count}\n"
            f"Columns:\n" + "\n".join(col_lines) + sample_str
        )


def _qt(name: str) -> str:
    """Quote a table or schema name that may contain spaces or reserved words."""
    return f'"{name}"'


def _get_foreign_keys(conn: sqlite3.Connection, schema: str, table: str) -> dict[str, str]:
    """Return {from_column: 'to_table.to_column'} for all FKs in the table."""
    fk_map: dict[str, str] = {}
    try:
        rows = conn.execute(f"PRAGMA {schema}.foreign_key_list({_qt(table)})").fetchall()
        for row in rows:
            # row: id, seq, table, from, to, on_update, on_delete, match
            fk_map[row[3]] = f"{row[2]}.{row[4]}"
    except Exception:
        pass
    return fk_map


def _get_row_count(conn: sqlite3.Connection, schema: str, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {schema}.{_qt(table)}").fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def _get_sample_rows(
    conn: sqlite3.Connection, schema: str, table: str, n: int = 3
) -> list[dict]:
    try:
        cursor = conn.execute(f"SELECT * FROM {schema}.{_qt(table)} LIMIT {n}")
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, r)) for r in cursor.fetchall()]
    except Exception:
        return []


def extract_table(schema: str, table: str) -> TableMeta:
    with managed_connection() as conn:
        fk_map = _get_foreign_keys(conn, schema, table)

        pragma_rows = conn.execute(
            f"PRAGMA {schema}.table_info({_qt(table)})"
        ).fetchall()
        # pragma columns: cid, name, type, notnull, dflt_value, pk

        columns = []
        for row in pragma_rows:
            _, name, col_type, not_null, default, pk = row
            is_fk = name in fk_map
            columns.append(
                ColumnMeta(
                    name=name,
                    type=col_type or "TEXT",
                    not_null=bool(not_null),
                    default_value=default,
                    is_primary_key=bool(pk),
                    is_foreign_key=is_fk,
                    references=fk_map.get(name),
                )
            )

        row_count = _get_row_count(conn, schema, table)
        sample_rows = _get_sample_rows(conn, schema, table)

    return TableMeta(
        schema=schema,
        table=table,
        columns=columns,
        row_count=row_count,
        sample_rows=sample_rows,
    )


def extract_all() -> list[TableMeta]:
    """Crawl every schema and table and return the full catalog."""
    catalog: list[TableMeta] = []
    for schema in list_schemas():
        tables = list_tables(schema)
        for table in tables:
            try:
                meta = extract_table(schema, table)
                catalog.append(meta)
            except Exception as e:
                print(f"[warn] Skipping {schema}.{table}: {e}")
    return catalog


def catalog_summary(catalog: list[TableMeta]) -> str:
    lines = []
    by_schema: dict[str, list[TableMeta]] = {}
    for m in catalog:
        by_schema.setdefault(m.schema, []).append(m)

    for schema, tables in sorted(by_schema.items()):
        lines.append(f"\n{schema} ({len(tables)} tables):")
        for t in sorted(tables, key=lambda x: x.table):
            lines.append(f"  {t.table:30s}  {t.row_count:>7,} rows  {len(t.columns)} cols")

    total_tables = len(catalog)
    total_rows = sum(t.row_count for t in catalog)
    lines.append(f"\nTotal: {total_tables} tables, {total_rows:,} rows")
    return "\n".join(lines)


if __name__ == "__main__":
    print("Extracting metadata from all schemas…")
    catalog = extract_all()
    print(catalog_summary(catalog))
    print("\nSample — first table description:")
    print(catalog[0].as_text())
