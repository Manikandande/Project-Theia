"""
SQL agent — answers data questions by writing and executing SQL.

Returns a structured dict with:
  narrative  — Theia's plain-English explanation
  rows       — raw data rows (max MAX_DISPLAY_ROWS for UI rendering)
  columns    — column names
  chart_type — "bar" | "line" | "area" | None (auto-detected)
  total_rows — how many rows the query actually returned
"""

from __future__ import annotations

import re

from catalog.metadata_extractor import extract_table
from config.settings import settings
from connectors.sqlite_connector import execute_query
from rag.pipeline import _call_ollama
from rag.retriever import retrieve
from security.guardrail import THEIA_SYSTEM_PROMPT

MAX_DISPLAY_ROWS = 10

_SQL_WRITER_PROMPT = """You are a SQLite expert. Your only job is to write a single, correct SQLite SELECT query.

Rules:
- Output ONLY the SQL query. No explanation, no markdown, no backticks.
- Use only SELECT or WITH statements — never INSERT, UPDATE, DELETE, DROP.
- ALWAYS double-quote table and column names that contain spaces or special characters: e.g. sales."Order Details"
- Schema-qualify every table: music.Album, sales.Orders, rental.film, geography.Country
- IMPORTANT join rules for the geography schema:
    geography.Country primary key is "Code" (not "CountryCode")
    geography.City.CountryCode references geography.Country.Code
    geography.CountryLanguage.CountryCode references geography.Country.Code
    Correct join: geography.City c JOIN geography.Country co ON c.CountryCode = co.Code
- Limit results to {max_rows} rows unless the question asks for an exact count or total.
- If you cannot write a query with the given context, output exactly: CANNOT_GENERATE

Available schema context:
{schema_context}

Question: {question}
"""

_EXPLAIN_PROMPT = """You are Theia, a data intelligence assistant. Explain the following query results in plain English.

- Be concise but insightful — 2-4 sentences maximum
- Highlight anything notable (high values, nulls, patterns)
- Do not mention SQL or show any code
- Speak in first person as Theia
- Do NOT list out every row — the user can see the table; just summarise the finding

Question that was asked: {question}

Query results ({row_count} rows returned, showing up to {display_rows}):
{results}
"""

_CHART_EXPLAIN_PROMPT = """You are Theia, a data intelligence assistant. The user asked for a chart.
The chart is being rendered automatically by the interface below your response — you do NOT need to generate it.

Write exactly 2 sentences:
1. Confirm what the chart shows: start with "Here is a [bar/line] chart showing..."
2. State the key insight or pattern visible in the data.

Do NOT say you cannot generate charts. Do NOT list the data rows. Do NOT use bullet points.

Question: {question}

Data used ({row_count} rows):
{results}
"""

_TIME_KEYWORDS = {"date", "month", "year", "quarter", "week", "day", "time", "period", "trend"}
_BAR_KEYWORDS  = {"count", "total", "sum", "average", "avg", "per", "by", "top", "bottom",
                   "most", "least", "highest", "lowest", "rank", "compare", "comparison"}


def _detect_chart_type(question: str, rows: list[dict]) -> str | None:
    """Guess the best chart type from the question wording and data shape.

    Only auto-charts results with exactly 2 columns (one label + one metric).
    Wide/raw row-dump queries (3+ columns) never get an automatic chart.
    """
    if not rows or len(rows) < 2:
        return None
    cols = list(rows[0].keys())
    if len(cols) != 2:
        return None

    def is_numeric(v) -> bool:
        try:
            float(v)
            return True
        except (TypeError, ValueError):
            return False

    numeric_cols = [c for c in cols if is_numeric(rows[0].get(c))]
    if not numeric_cols:
        return None

    q_lower = question.lower()
    if any(kw in q_lower for kw in _TIME_KEYWORDS):
        return "line"
    return "bar"


def _extract_sql(raw: str) -> str | None:
    raw = raw.strip()
    fenced = re.search(r"```(?:sql)?\s*([\s\S]+?)```", raw, re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    if raw.upper().startswith(("SELECT", "WITH")):
        return raw
    return None


def _build_schema_context(table_ids: list[str]) -> str:
    lines = []
    for tid in table_ids:
        parts = tid.split(".")
        if len(parts) != 2:
            continue
        schema, table = parts
        try:
            meta = extract_table(schema, table)
            col_desc = ", ".join(
                f"{c.name} {c.type}"
                + (" PK" if c.is_primary_key else "")
                + (f" FK→{c.references}" if c.is_foreign_key else "")
                for c in meta.columns
            )
            lines.append(f"{schema}.{table}: {col_desc}")
        except Exception:
            lines.append(tid)
    return "\n".join(lines)


def _format_for_llm(rows: list[dict], n: int = MAX_DISPLAY_ROWS) -> str:
    if not rows:
        return "(no rows returned)"
    keys = list(rows[0].keys())
    header = " | ".join(keys)
    divider = "-" * len(header)
    lines = [" | ".join(str(r.get(k, "")) for k in keys) for r in rows[:n]]
    return f"{header}\n{divider}\n" + "\n".join(lines)


def answer(question: str, chart_requested: bool = False) -> dict:
    """
    Answer a data question. Returns a dict:
      narrative      — Theia's plain-English summary
      rows           — list of dicts, max MAX_DISPLAY_ROWS
      columns        — column names
      chart_type     — "bar" | "line" | None
      total_rows     — actual number of rows the query returned
    """
    _error_result = lambda msg: {
        "narrative": msg, "rows": [], "columns": [],
        "chart_type": None, "total_rows": 0,
    }

    results = retrieve(question, top_k=6)
    table_ids = [r["id"] for r in results]
    schema_context = _build_schema_context(table_ids)

    sql_prompt = _SQL_WRITER_PROMPT.format(
        max_rows=settings.max_sql_rows,
        schema_context=schema_context,
        question=question,
    )
    raw_sql = _call_ollama(
        "You are a SQLite SQL writer. Output only SQL, nothing else.",
        sql_prompt,
    )
    sql = _extract_sql(raw_sql)
    if not sql or "CANNOT_GENERATE" in raw_sql:
        return _error_result(
            "I couldn't construct a query for that question with the context I have. "
            "Could you rephrase it, or tell me which table or schema you're asking about?"
        )

    try:
        all_rows = execute_query(sql)
    except ValueError as e:
        return _error_result(f"I wasn't able to run that query safely: {e}")
    except Exception as e:
        return _error_result(
            f"I ran into an issue querying the database: {e}. "
            "Try rephrasing your question or specifying the table name."
        )

    display_rows = all_rows[:MAX_DISPLAY_ROWS]
    columns = list(all_rows[0].keys()) if all_rows else []

    # Determine chart type — auto-detect or force "bar" when explicitly requested
    chart_type = _detect_chart_type(question, display_rows)
    if chart_requested and not chart_type and display_rows:
        chart_type = "bar"

    # Use chart-specific prompt when the user asked for a chart
    if chart_requested and chart_type:
        prompt = _CHART_EXPLAIN_PROMPT.format(
            question=question,
            row_count=len(all_rows),
            results=_format_for_llm(all_rows),
        )
    else:
        prompt = _EXPLAIN_PROMPT.format(
            question=question,
            row_count=len(all_rows),
            display_rows=MAX_DISPLAY_ROWS,
            results=_format_for_llm(all_rows),
        )

    narrative = _call_ollama(THEIA_SYSTEM_PROMPT, prompt)

    return {
        "narrative": narrative,
        "rows": display_rows,
        "columns": columns,
        "chart_type": chart_type,
        "total_rows": len(all_rows),
    }
