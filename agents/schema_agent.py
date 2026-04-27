"""
Schema agent — answers structural questions about the data landscape.

Examples:
  "What tables are in the music schema?"
  "How are Artist and Album related?"
  "What columns does the Invoice table have?"
  "Which tables have a foreign key to Customer?"

Uses the catalog directly — no SQL execution needed.
"""

from __future__ import annotations

from catalog.data_profiler import profile_table
from catalog.metadata_extractor import extract_all, extract_table
from connectors.sqlite_connector import list_schemas, list_tables
from rag.pipeline import _call_ollama, retrieve_context_blocks
from security.guardrail import THEIA_SYSTEM_PROMPT, build_rag_prompt


def _build_schema_context(schema: str | None = None) -> str:
    """Build a comprehensive schema map for context injection."""
    lines = []
    schemas = [schema] if schema else list_schemas()
    for s in schemas:
        tables = list_tables(s)
        lines.append(f"Schema: {s} ({len(tables)} tables)")
        for t in tables:
            try:
                meta = extract_table(s, t)
                pk_cols = [c.name for c in meta.columns if c.is_primary_key]
                fk_cols = [f"{c.name}→{c.references}" for c in meta.columns if c.is_foreign_key]
                lines.append(f"  {t} ({meta.row_count:,} rows)")
                if pk_cols:
                    lines.append(f"    PK: {', '.join(pk_cols)}")
                if fk_cols:
                    lines.append(f"    FK: {', '.join(fk_cols)}")
            except Exception:
                lines.append(f"  {t}")
    return "\n".join(lines)


def _find_mentioned_table(question: str) -> tuple[str | None, str | None]:
    """Detect the most specific table name mentioned in the question.

    Prefers longer names so 'invoiceline' beats 'invoice' as a substring.
    """
    q_lower = question.lower()
    best_schema, best_table = None, None
    best_len = 0
    for schema in list_schemas():
        for table in list_tables(schema):
            tl = table.lower()
            if tl in q_lower and len(tl) > best_len:
                best_schema, best_table = schema, table
                best_len = len(tl)
    return best_schema, best_table


_SCHEMA_ANSWER_SUFFIX = (
    "\n\nIMPORTANT RULES FOR THIS RESPONSE:\n"
    "- Describe relationships and structure in plain prose only.\n"
    "- Do NOT invent, fabricate, or show any data rows, sample values, or data tables.\n"
    "- Do NOT generate any charts, rankings, or top-N lists — those require actual SQL queries.\n"
    "- Only state facts visible in the schema context provided above."
)


def answer(question: str, schema_hint: str | None = None) -> str:
    """
    Answer a schema/structural question about the data.

    schema_hint: if the question mentions a specific schema, pass it here
                 to narrow the context and speed up the response.
    """
    mentioned_schema, mentioned_table = _find_mentioned_table(question)
    direct_blocks = []
    if mentioned_schema and mentioned_table:
        try:
            meta = extract_table(mentioned_schema, mentioned_table)
            direct_blocks.append(meta.as_text())
        except Exception:
            pass

    rag_blocks = retrieve_context_blocks(question, top_k=4)
    schema_map = _build_schema_context(schema_hint)
    context_blocks = direct_blocks + rag_blocks + [f"Full schema map:\n{schema_map}"]

    user_prompt = build_rag_prompt(question, context_blocks) + _SCHEMA_ANSWER_SUFFIX
    return _call_ollama(THEIA_SYSTEM_PROMPT, user_prompt)


_DESCRIBE_TABLE_PROMPT = """You are Theia, a data intelligence assistant. A user wants to understand what a database table is about and how it connects to other tables.

STRICT RULES:
- Write flowing prose only — no invented data tables, no fabricated rankings, no markdown tables.
- Base every statement only on the schema and sample data provided below.
- Do NOT claim to show a chart or top-N list — those require separate queries.
- Be specific about foreign key relationships: name the columns and the tables they link to.

Answer in 4–6 sentences of plain, flowing prose:
1. What does this table represent in the real world?
2. What are the most important columns and what do they store?
3. How does it connect to other tables? (use the FK list — be specific, e.g. "ArtistId links this table to the Artist table")
4. Any notable characteristics (row count, patterns, purpose in the overall schema)?

Table profile:
{profile_text}

Foreign key relationships:
{fk_text}

Sample data (first 5 rows):
{sample_text}
"""


def describe_table(schema: str, table: str) -> str:
    """
    Generate a data-aware plain-English description of a table.

    Feeds real sample rows + profiling stats + FK relationships to Llama
    and asks it to explain what the table represents in the real world.
    """
    try:
        # Get rich profiling data (includes sample rows, stats, column types)
        tp = profile_table(schema, table)
        meta = tp.meta

        # Format sample rows clearly
        if meta.sample_rows:
            keys = list(meta.sample_rows[0].keys())
            sample_lines = [" | ".join(str(v) for v in row.values()) for row in meta.sample_rows[:5]]
            sample_text = "Columns: " + " | ".join(keys) + "\n" + "\n".join(sample_lines)
        else:
            sample_text = "(no sample rows available)"

        # Format FK relationships
        fk_rels = [
            f"{c.name} → {c.references}"
            for c in meta.columns if c.is_foreign_key
        ]
        fk_text = "\n".join(fk_rels) if fk_rels else "No foreign keys (this may be a root/lookup table)"

        # Full column+stats profile text
        profile_text = tp.as_text()

        prompt = _DESCRIBE_TABLE_PROMPT.format(
            profile_text=profile_text,
            fk_text=fk_text,
            sample_text=sample_text,
        )
        return _call_ollama(THEIA_SYSTEM_PROMPT, prompt)

    except Exception as e:
        return f"I wasn't able to generate a description for `{schema}.{table}`: {e}"


def column_metadata(schema: str, table: str) -> list[dict]:
    """
    Return structured column metadata for a specific table — for UI table rendering.

    Each dict: {Column, Type, Primary Key, Foreign Key}
    """
    try:
        meta = extract_table(schema, table)
        rows = []
        for c in meta.columns:
            rows.append({
                "Column": c.name,
                "Type": c.type or "TEXT",
                "Primary Key": "✓" if c.is_primary_key else "",
                "Foreign Key": c.references if c.is_foreign_key else "",
            })
        return rows
    except Exception:
        return []


def tables_metadata(schema: str) -> list[dict]:
    """Return one row per table in a schema — for UI table rendering."""
    rows = []
    for table in list_tables(schema):
        try:
            meta = extract_table(schema, table)
            rows.append({
                "Table": table,
                "Rows": f"{meta.row_count:,}",
                "Columns": len(meta.columns),
            })
        except Exception:
            rows.append({"Table": table, "Rows": "?", "Columns": "?"})
    return rows


def list_all_tables_summary() -> str:
    """Return a plain-text summary of all schemas and their tables."""
    lines = []
    for schema in list_schemas():
        tables = list_tables(schema)
        lines.append(f"\n{schema.upper()} schema — {len(tables)} tables:")
        for t in tables:
            lines.append(f"  • {t}")
    return "\n".join(lines)
