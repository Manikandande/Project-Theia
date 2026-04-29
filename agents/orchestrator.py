"""
Orchestrator — classifies the user's question and routes it to the right agent.

Intent categories:
  SCHEMA       → schema_agent  (structure, column names, relationships)
  COLUMN_META  → schema_agent  (user asks for column list → returns metadata table)
  TABLE_META   → schema_agent  (user asks for tables in a schema → returns metadata table)
  DATA         → sql_agent     (actual values, aggregations, top-N lookups)
  PROFILE      → profiler_agent (statistical summary)
  ROW_LIMIT    → refused       (user asked for more than MAX_DISPLAY_ROWS rows)
  OFF_TOPIC    → guardrail     (rejected immediately)
  GENERAL      → rag/pipeline  (fallback)

Every result dict always has the same shape:
  answer      str
  intent      str
  sources     list[str]
  rows        list[dict] | None   ← raw data for st.dataframe()
  columns     list[str] | None    ← column names list
  chart_type  str | None          ← "bar" | "line" | None
  meta_table  list[dict] | None   ← structured metadata for st.dataframe()
"""

from __future__ import annotations

import re
import time

from agents.sql_agent import MAX_DISPLAY_ROWS
from connectors.sqlite_connector import list_schemas, list_tables
from rag.pipeline import _call_ollama
from security.audit_logger import log_interaction
from security.guardrail import OUT_OF_DOMAIN_RESPONSE, is_likely_off_topic
from security.pii_detector import mask


# ── Routing signals ───────────────────────────────────────────────────────────

_SCHEMA_SIGNALS = [
    "what tables", "which tables", "list tables", "how are", "related to",
    "foreign key", "primary key", "schema", "what is the structure",
    "what does.*column.*mean",
]

_DESCRIBE_TABLE_SIGNALS = [
    r"describe",
    r"tell me about",
    r"know about",
    r"learn about",
    r"what is (the |).*table",
    r"what does (the |).*table (store|contain|hold|represent)",
    r"explain (the |).*table",
    r"what('s| is) (in|stored in|inside)",
    r"meaning of",
    r"purpose of",
    r"relationship",
    r"related to",
    r"how does.*connect",
    r"how.*link",
    r"foreign key",
]

_COLUMN_META_SIGNALS = [
    r"what (are the |are |)columns",
    r"which (are the |are |)columns",
    r"show (me )?(the |)columns",
    r"list (the |)columns",
    r"column names",
    r"what fields",
    r"show (me )?(the |)fields",
    r"(columns|fields) (in|of|for)",
    r"metadata",
    r"print.*column",
    r"display.*column",
]

_TABLE_META_SIGNALS = [
    r"what tables",
    r"which tables",
    r"list (the |all |)tables",
    r"show (me )?(the |all |)tables",
    r"tables in (the |)",
]

_PROFILE_SIGNALS = [
    "profile", "statistics", "stats", "null", "nulls", "distribution",
    "how many rows", "row count", "summarize the table", "summarise",
    "what does.*table look like", "overview of",
]

_DIAGRAM_SIGNALS = [
    r"display.*relation", r"show.*relation", r"visuali[sz].*relation",
    r"relationship.*diagram", r"relationship.*map", r"table.*relation",
    r"relation.*table", r"diagram", r"pictori", r"draw.*relation",
    r"map.*relation", r"how.*tables.*connect", r"how.*tables.*related",
    r"entity.{0,10}relation", r"\berd\b",
]

_CHART_SIGNALS = [
    r"chart", r"graph", r"plot", r"visuali[sz]e?", r"visuali[sz]ation",
    r"bar chart", r"line chart", r"bar graph", r"line graph",
    r"show.*graph", r"draw.*chart", r"create.*chart", r"generate.*chart",
    r"trend", r"over time", r"by month", r"by year", r"distribution",
]

_DATA_SIGNALS = [
    "who is", "who are", "show me", "print", "display",
    "find", "get", "fetch", "top ", "bottom ", "highest", "lowest",
    "most", "least", "how many", "count", "total", "sum", "average", "avg",
    "biggest", "smallest", "largest", "first", "last", "latest", "oldest",
    "between", "where", "filter", "lookup", "search",
]

# Numbers that signal a large row request (>MAX_DISPLAY_ROWS)
_LARGE_N_RE = re.compile(
    r"\b(?:top|first|last|show|print|display|list|get|fetch)?\s*(\d+)\s*"
    r"(?:rows?|records?|entries|results?|items?)\b",
    re.IGNORECASE,
)
_TOP_N_RE = re.compile(r"\btop\s+(\d+)\b", re.IGNORECASE)
_ALL_RE   = re.compile(r"\b(all|every|entire)\b.*(?:rows?|records?|data|table)", re.IGNORECASE)


def _requested_row_count(question: str) -> int | None:
    """Return the explicitly requested row count, or None if not specified."""
    for pattern in (_LARGE_N_RE, _TOP_N_RE):
        m = pattern.search(question)
        if m:
            return int(m.group(1))
    if _ALL_RE.search(question):
        return 999_999
    return None


def _matches_any(question: str, signals: list[str]) -> bool:
    q = question.lower()
    return any(re.search(sig, q) for sig in signals)


def _table_matches(table: str, q_lower: str) -> bool:
    tl = table.lower()
    if tl in q_lower:
        return True
    if tl.endswith("s") and tl[:-1] in q_lower:
        return True
    if (tl + "s") in q_lower:
        return True
    return False


def _detect_schema_and_table(question: str) -> tuple[str | None, str | None]:
    q_lower = question.lower()

    detected_schema = None
    for schema in list_schemas():
        if schema in q_lower:
            detected_schema = schema
            break

    search_order = (
        [detected_schema] + [s for s in list_schemas() if s != detected_schema]
        if detected_schema else list_schemas()
    )

    detected_table = None
    best_len = 0
    for schema in search_order:
        for table in list_tables(schema):
            if _table_matches(table, q_lower) and len(table) > best_len:
                if detected_schema is None:
                    detected_schema = schema
                detected_table = table
                best_len = len(table)
        if detected_table and schema == search_order[0]:
            break

    return detected_schema, detected_table


def _empty_result(answer: str, intent: str, sources: list[str] | None = None) -> dict:
    return {
        "answer": answer, "intent": intent,
        "sources": sources or [],
        "rows": None, "columns": None,
        "chart_type": None, "meta_table": None,
    }


# ── Conversation context resolver ────────────────────────────────────────────

_VAGUE_SIGNALS = (
    "this", "that", " it", "same", "above", "previous",
    "also show", "as well", "instead", "the chart", "the result",
    "the data", "the table", "those", "these", "convert this",
)

_RESOLVE_SYSTEM = "You are a query resolver. Output ONLY the resolved question, nothing else."

_RESOLVE_PROMPT = """\
A user is chatting with a data intelligence assistant. They asked a follow-up question \
that uses vague references ("this", "that", "it", "the result", etc.).

Rewrite their follow-up as a COMPLETE, SELF-CONTAINED question that includes all \
necessary specifics (table name, schema, metric, chart type, etc.) inferred from history.

Rules:
- Output ONLY the resolved question. No explanation, no prefix like "Resolved:".
- Replace every vague reference with the specific entity from the history.
- If the question is already self-contained (no vague references), return it unchanged.

Conversation history:
{history}

Follow-up question: {question}"""


def _resolve_question(question: str, history: list[dict]) -> str:
    """Expand vague follow-up questions into self-contained ones using history."""
    q_lower = question.lower()
    if not history or not any(sig in q_lower for sig in _VAGUE_SIGNALS):
        return question

    history_text = "\n".join(
        f"{m['role'].capitalize()}: {m['content'][:400]}"
        for m in history[-6:]
    )
    prompt = _RESOLVE_PROMPT.format(history=history_text, question=question)
    resolved = _call_ollama(_RESOLVE_SYSTEM, prompt).strip()
    for line in resolved.splitlines():
        line = line.strip()
        if line:
            return line
    return question


def route(question: str, history: list[dict] | None = None) -> dict:
    """
    Classify the question, call the right agent, and return a unified result dict.
    history: list of {role, content} dicts from recent conversation turns.
    """
    if history:
        question = _resolve_question(question, history)
    if is_likely_off_topic(question):
        return _empty_result(OUT_OF_DOMAIN_RESPONSE, "off_topic")

    schema_hint, table_hint = _detect_schema_and_table(question)

    # ── Row-limit guard (before any SQL work) ─────────────────────────────────
    requested = _requested_row_count(question)
    if requested and requested > MAX_DISPLAY_ROWS:
        msg = (
            f"I can display up to **{MAX_DISPLAY_ROWS} rows** at a time to keep things "
            f"readable. You asked for {requested if requested < 999_999 else 'all'} rows — "
            f"I'm not allowed to display more than {MAX_DISPLAY_ROWS}. "
            f"Try asking for a summary, an aggregation, or the top {MAX_DISPLAY_ROWS} instead."
        )
        return _empty_result(msg, "row_limit")

    # ── Column metadata (structured table of column names + types) ────────────
    if _matches_any(question, _COLUMN_META_SIGNALS) and table_hint:
        from agents.schema_agent import column_metadata, describe_table
        description = describe_table(schema_hint or "", table_hint)
        meta = column_metadata(schema_hint or "", table_hint)
        return {
            **_empty_result(description, "column_meta",
                            [f"{schema_hint}.{table_hint}"] if schema_hint else []),
            "meta_table": meta,
            "columns": ["Column", "Type", "Primary Key", "Foreign Key"],
        }

    # ── Table list metadata (structured table of tables in a schema) ──────────
    # Only fires when the user asks about tables in a schema generically —
    # NOT when they mention a specific table (that's a relationship/describe question).
    if _matches_any(question, _TABLE_META_SIGNALS) and schema_hint and not table_hint:
        from agents.schema_agent import answer as schema_answer, tables_metadata
        narrative = schema_answer(question, schema_hint=schema_hint)
        meta = tables_metadata(schema_hint)
        return {
            **_empty_result(narrative, "table_meta", []),
            "meta_table": meta,
            "columns": ["Table", "Rows", "Columns"],
        }

    # ── Describe table (data-aware meaning) ──────────────────────────────────
    if _matches_any(question, _DESCRIBE_TABLE_SIGNALS) and table_hint:
        from agents.schema_agent import column_metadata, describe_table
        description = describe_table(schema_hint or "", table_hint)
        meta = column_metadata(schema_hint or "", table_hint)
        return {
            **_empty_result(description, "describe_table",
                            [f"{schema_hint}.{table_hint}"] if schema_hint else []),
            "meta_table": meta,
            "columns": ["Column", "Type", "Primary Key", "Foreign Key"],
        }

    # ── Profile intent ────────────────────────────────────────────────────────
    if _matches_any(question, _PROFILE_SIGNALS) and table_hint:
        from agents.profiler_agent import answer as profiler_answer
        narrative = profiler_answer(question, schema_hint, table_hint)
        return _empty_result(
            narrative, "profile",
            [f"{schema_hint}.{table_hint}"] if schema_hint else [],
        )

    # ── Relationship diagram — pictorial/Unicode ERD for a whole schema ───────
    # Fires when the user asks to *see* relationships (not just read about them)
    # and no specific table is mentioned (that would be describe_table instead).
    if _matches_any(question, _DIAGRAM_SIGNALS) and schema_hint and not table_hint:
        from agents.schema_agent import generate_relationship_diagram
        diagram = generate_relationship_diagram(schema_hint)
        return _empty_result(diagram, "diagram", [f"{schema_hint}.*"])

    # ── General schema/structural intent ─────────────────────────────────────
    if _matches_any(question, _SCHEMA_SIGNALS):
        from agents.schema_agent import answer as schema_answer
        narrative = schema_answer(question, schema_hint=schema_hint)
        return _empty_result(narrative, "schema")

    # ── Chart intent — user explicitly wants a visualisation ─────────────────
    if _matches_any(question, _CHART_SIGNALS):
        from agents.sql_agent import answer as sql_answer
        result = sql_answer(question, chart_requested=True)
        return {
            "answer": result["narrative"],
            "intent": "chart",
            "sources": [],
            "rows": result["rows"] if result["rows"] else None,
            "columns": result["columns"] if result["columns"] else None,
            "chart_type": result["chart_type"] or "bar",
            "meta_table": None,
        }

    # ── Data intent — needs live SQL ──────────────────────────────────────────
    if _matches_any(question, _DATA_SIGNALS):
        from agents.sql_agent import answer as sql_answer
        result = sql_answer(question)
        return {
            "answer": result["narrative"],
            "intent": "data",
            "sources": [],
            "rows": result["rows"] if result["rows"] else None,
            "columns": result["columns"] if result["columns"] else None,
            "chart_type": result["chart_type"],
            "meta_table": None,
        }

    # ── Fallback RAG ──────────────────────────────────────────────────────────
    from rag.pipeline import ask
    rag = ask(question)
    return {
        **_empty_result(rag["answer"], "general", rag.get("sources", [])),
    }


def ask_theia(question: str) -> str:
    """Entry point with PII masking + audit logging. Returns answer string only."""
    start = time.monotonic()
    original_question = question
    masked_question, pii_found = mask(question)
    result = route(masked_question)
    result["pii_masked"] = pii_found
    duration_ms = int((time.monotonic() - start) * 1000)
    log_interaction(
        question=original_question,
        answer=result["answer"],
        intent=result["intent"],
        sources=result.get("sources", []),
        pii_masked=pii_found,
        duration_ms=duration_ms,
    )
    return result["answer"]
