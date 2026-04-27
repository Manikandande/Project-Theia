"""
Theia FastAPI server.

Run with:
    PYTHONPATH=. uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
    POST /chat          — ask Theia a question
    GET  /catalog       — list all schemas and tables
    GET  /profile/{schema}/{table} — profile a specific table
    GET  /audit         — recent audit log entries
    GET  /health        — liveness check
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="Theia — Data Intelligence API",
    description="Private, on-premise AI data intelligence assistant.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],   # Streamlit dev origin
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str

class ChatResponse(BaseModel):
    answer: str
    intent: str
    sources: list[str]
    pii_masked: bool


class TableSummary(BaseModel):
    schema: str
    table: str
    row_count: int
    col_count: int


class CatalogResponse(BaseModel):
    schemas: dict[str, list[str]]
    total_tables: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "theia"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """Ask Theia a question. PII is masked and the interaction is logged."""
    from agents.orchestrator import route
    from security.audit_logger import log_interaction
    from security.pii_detector import mask as pii_mask
    import time

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    start = time.monotonic()
    masked_q, pii_found = pii_mask(req.question)
    result = route(masked_q)
    duration_ms = int((time.monotonic() - start) * 1000)

    log_interaction(
        question=req.question,
        answer=result["answer"],
        intent=result["intent"],
        sources=result.get("sources", []),
        pii_masked=pii_found,
        duration_ms=duration_ms,
    )

    return ChatResponse(
        answer=result["answer"],
        intent=result["intent"],
        sources=result.get("sources", []),
        pii_masked=pii_found,
    )


@app.get("/catalog", response_model=CatalogResponse)
def catalog():
    """Return all schemas and their table names."""
    from connectors.sqlite_connector import list_schemas, list_tables

    schemas = {}
    total = 0
    for schema in list_schemas():
        tables = list_tables(schema)
        schemas[schema] = tables
        total += len(tables)

    return CatalogResponse(schemas=schemas, total_tables=total)


@app.get("/profile/{schema}/{table}")
def profile(schema: str, table: str):
    """Return a plain-English profile of a specific table."""
    from agents.profiler_agent import answer as profiler_answer
    from connectors.sqlite_connector import list_schemas, list_tables

    if schema not in list_schemas():
        raise HTTPException(status_code=404, detail=f"Schema '{schema}' not found.")
    if table not in list_tables(schema):
        raise HTTPException(status_code=404, detail=f"Table '{table}' not found in schema '{schema}'.")

    question = f"Profile the {table} table in the {schema} schema."
    text = profiler_answer(question, schema, table)
    return {"schema": schema, "table": table, "profile": text}


@app.get("/audit")
def audit(limit: int = 20):
    """Return the most recent audit log entries."""
    from security.audit_logger import audit_stats, recent_logs

    return {
        "stats": audit_stats(),
        "recent": recent_logs(min(limit, 100)),
    }


@app.post("/reindex")
def reindex(force: bool = False):
    """Trigger a schema change check and selective re-index."""
    from learning.reindexer import full_reindex, reindex_changed

    if force:
        n = full_reindex(verbose=False)
        return {"status": "full_reindex", "tables_indexed": n}
    else:
        summary = reindex_changed(verbose=False)
        return {"status": "incremental", **summary}
