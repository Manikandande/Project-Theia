"""
Audit logger — writes every question and answer to a local SQLite audit trail.

Schema:
  audit_log(
    id          INTEGER PRIMARY KEY,
    timestamp   TEXT,        -- ISO-8601
    question    TEXT,        -- original (pre-masking) question
    masked      INTEGER,     -- 1 if PII was detected and masked
    intent      TEXT,        -- schema | data | profile | off_topic | general
    sources     TEXT,        -- comma-separated table IDs used as context
    answer      TEXT,        -- Theia's response
    duration_ms INTEGER      -- wall-clock time for the full request
  )

The audit DB is separate from the data databases so it is never
accidentally queried or modified by Theia's SQL agent.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from config.settings import settings


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.audit_log_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            question    TEXT    NOT NULL,
            masked      INTEGER NOT NULL DEFAULT 0,
            intent      TEXT    NOT NULL DEFAULT 'unknown',
            sources     TEXT    NOT NULL DEFAULT '',
            answer      TEXT    NOT NULL DEFAULT '',
            duration_ms INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def log_interaction(
    question: str,
    answer: str,
    intent: str = "unknown",
    sources: list[str] | None = None,
    pii_masked: bool = False,
    duration_ms: int = 0,
) -> None:
    """Write one question-answer pair to the audit log."""
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO audit_log
               (timestamp, question, masked, intent, sources, answer, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                question,
                int(pii_masked),
                intent,
                ", ".join(sources or []),
                answer,
                duration_ms,
            ),
        )
        conn.commit()
    finally:
        conn.close()


@contextmanager
def timed_interaction(question: str):
    """
    Context manager that measures wall-clock time.

    Usage:
        with timed_interaction(question) as ctx:
            result = route(question)
            ctx['result'] = result
        # automatically logs after the block exits
    """
    ctx: dict = {}
    start = time.monotonic()
    yield ctx
    duration_ms = int((time.monotonic() - start) * 1000)
    result = ctx.get("result", {})
    log_interaction(
        question=question,
        answer=result.get("answer", ""),
        intent=result.get("intent", "unknown"),
        sources=result.get("sources", []),
        pii_masked=result.get("pii_masked", False),
        duration_ms=duration_ms,
    )


def recent_logs(n: int = 20) -> list[dict]:
    """Return the n most recent audit log entries."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM audit_log LIMIT 0").description or []]
        # Rebuild column names from CREATE TABLE
        cols = ["id", "timestamp", "question", "masked", "intent", "sources", "answer", "duration_ms"]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


def audit_stats() -> dict:
    """Return summary statistics about the audit log."""
    conn = _get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        intents = conn.execute(
            "SELECT intent, COUNT(*) FROM audit_log GROUP BY intent"
        ).fetchall()
        pii_count = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE masked=1"
        ).fetchone()[0]
        avg_ms = conn.execute("SELECT AVG(duration_ms) FROM audit_log").fetchone()[0]
        return {
            "total_questions": total,
            "pii_detected": pii_count,
            "avg_response_ms": round(avg_ms or 0),
            "by_intent": dict(intents),
        }
    finally:
        conn.close()
