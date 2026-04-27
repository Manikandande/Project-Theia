"""
Retriever — semantic search over the ChromaDB schema index.

Given a natural language question, returns the top-k most relevant
table descriptions. These become the CONTEXT block in Theia's prompt.
"""

from __future__ import annotations

from embeddings.chroma_store import search
from embeddings.schema_embedder import embed_text
from config.settings import settings


def retrieve(question: str, top_k: int | None = None) -> list[dict]:
    """
    Embed the question and return the top-k closest table profiles.

    Each result dict has:
      id        — "{schema}.{table}"
      document  — the full profiled text description
      metadata  — schema, table, row_count, col_count
      distance  — cosine distance (lower = more similar)
    """
    k = top_k or settings.retriever_top_k
    vec = embed_text(question)
    return search(vec, top_k=k)


def retrieve_context_blocks(question: str, top_k: int | None = None) -> list[str]:
    """Return just the text descriptions, ready to inject into a prompt."""
    results = retrieve(question, top_k=top_k)
    return [r["document"] for r in results]


def retrieve_table_ids(question: str, top_k: int | None = None) -> list[str]:
    """Return just the table IDs (e.g. ['music.Invoice', 'sales.Orders'])."""
    results = retrieve(question, top_k=top_k)
    return [r["id"] for r in results]
