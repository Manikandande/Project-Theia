"""
Data profiler — extends TableMeta with per-column statistics.

For each column it computes:
  - null_count / null_pct
  - distinct_count
  - For numerics: min, max, avg
  - For text/dates: top 5 most frequent values

The profiled description is richer than plain schema text, giving Theia
the ability to mention "3% of orders have a null ship_date" naturally.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from catalog.metadata_extractor import ColumnMeta, TableMeta, extract_table
from connectors.sqlite_connector import list_schemas, list_tables, managed_connection

_NUMERIC_TYPES = {"INTEGER", "INT", "REAL", "FLOAT", "NUMERIC", "DECIMAL", "DOUBLE", "BIGINT"}
_BLOB_TYPES = {"BLOB", "BYTEA", "BINARY", "VARBINARY", "IMAGE", "PICTURE"}
_MAX_VALUE_REPR = 200   # max chars for any single top-value string


def _is_numeric(col_type: str) -> bool:
    return any(t in col_type.upper() for t in _NUMERIC_TYPES)


def _is_blob(col_type: str) -> bool:
    return any(t in col_type.upper() for t in _BLOB_TYPES) or col_type.strip() == ""


@dataclass
class ColumnProfile:
    column: ColumnMeta
    null_count: int = 0
    null_pct: float = 0.0
    distinct_count: int = 0
    # numeric
    min_val: Any = None
    max_val: Any = None
    avg_val: float | None = None
    # text / categorical
    top_values: list[Any] = field(default_factory=list)

    def as_text(self) -> str:
        parts = [f"{self.column.name} [{self.column.type}]"]
        if self.column.is_primary_key:
            parts.append("primary key")
        if self.column.is_foreign_key:
            parts.append(f"→ {self.column.references}")
        if self.null_pct > 0:
            parts.append(f"{self.null_pct:.1f}% null")
        parts.append(f"{self.distinct_count} distinct values")
        if self.min_val is not None:
            parts.append(f"range [{self.min_val} – {self.max_val}]")
        if self.avg_val is not None:
            parts.append(f"avg {self.avg_val:.2f}")
        if self.top_values:
            sample = ", ".join(str(v) for v in self.top_values[:5])
            parts.append(f"common values: {sample}")
        return " | ".join(parts)


@dataclass
class TableProfile:
    meta: TableMeta
    column_profiles: list[ColumnProfile] = field(default_factory=list)

    def as_text(self) -> str:
        col_lines = "\n".join(f"  {cp.as_text()}" for cp in self.column_profiles)
        return (
            f"Table: {self.meta.full_name}\n"
            f"Total rows: {self.meta.row_count:,}\n"
            f"Columns ({len(self.column_profiles)}):\n{col_lines}"
        )


def _profile_column(
    conn: sqlite3.Connection,
    schema: str,
    table: str,
    col: ColumnMeta,
    total_rows: int,
) -> ColumnProfile:
    qt = f'{schema}."{table}"'
    qc = f'"{col.name}"'
    profile = ColumnProfile(column=col)

    if total_rows == 0:
        return profile

    try:
        null_count = conn.execute(
            f"SELECT COUNT(*) FROM {qt} WHERE {qc} IS NULL"
        ).fetchone()[0]
        profile.null_count = null_count
        profile.null_pct = round(100.0 * null_count / total_rows, 2)
    except Exception:
        pass

    try:
        profile.distinct_count = conn.execute(
            f"SELECT COUNT(DISTINCT {qc}) FROM {qt}"
        ).fetchone()[0]
    except Exception:
        pass

    if _is_blob(col.type):
        # Skip binary columns entirely — raw bytes are meaningless for embeddings
        return profile

    if _is_numeric(col.type):
        try:
            row = conn.execute(
                f"SELECT MIN({qc}), MAX({qc}), AVG({qc}) FROM {qt}"
            ).fetchone()
            if row:
                profile.min_val = row[0]
                profile.max_val = row[1]
                profile.avg_val = round(row[2], 4) if row[2] is not None else None
        except Exception:
            pass
    else:
        try:
            rows = conn.execute(
                f"SELECT {qc}, COUNT(*) as cnt FROM {qt} "
                f"WHERE {qc} IS NOT NULL GROUP BY {qc} ORDER BY cnt DESC LIMIT 5"
            ).fetchall()
            # Truncate long values (e.g. base64-encoded blobs stored as TEXT)
            profile.top_values = [
                str(r[0])[:_MAX_VALUE_REPR] if r[0] is not None else None
                for r in rows
            ]
        except Exception:
            pass

    return profile


def profile_table(schema: str, table: str) -> TableProfile:
    meta = extract_table(schema, table)
    profiles: list[ColumnProfile] = []
    with managed_connection() as conn:
        for col in meta.columns:
            cp = _profile_column(conn, schema, table, col, meta.row_count)
            profiles.append(cp)
    return TableProfile(meta=meta, column_profiles=profiles)


def profile_all() -> list[TableProfile]:
    results: list[TableProfile] = []
    for schema in list_schemas():
        for table in list_tables(schema):
            try:
                tp = profile_table(schema, table)
                results.append(tp)
                print(f"  profiled {schema}.{table} ({tp.meta.row_count:,} rows)")
            except Exception as e:
                print(f"  [warn] skipping {schema}.{table}: {e}")
    return results


if __name__ == "__main__":
    print("Profiling all tables…\n")
    profiles = profile_all()
    print(f"\nDone. {len(profiles)} tables profiled.")
    print("\nSample profile:")
    print(profiles[0].as_text())
