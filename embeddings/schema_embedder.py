"""
Schema embedder — profiles every table, embeds the description via
nomic-embed-text (running locally in Ollama), and stores it in ChromaDB.

Run this once after setup, and again whenever schemas change (the
learning/reindexer.py module calls it selectively for changed tables).
"""

from __future__ import annotations

import time
from typing import Callable

import requests

from catalog.data_profiler import TableProfile, profile_all, profile_table
from config.settings import settings
from embeddings.chroma_store import count, reset, upsert_batch


_MAX_EMBED_CHARS = 8_000   # nomic-embed-text context ≈ 8192 tokens


def embed_text(text: str) -> list[float]:
    """Call Ollama's embedding API and return the vector."""
    if len(text) > _MAX_EMBED_CHARS:
        text = text[:_MAX_EMBED_CHARS]
    resp = requests.post(
        f"{settings.ollama_base_url}/api/embeddings",
        json={"model": settings.embed_model, "prompt": text},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def _profile_to_doc(tp: TableProfile) -> tuple[str, str, dict]:
    """Return (doc_id, text, metadata) for a TableProfile."""
    doc_id = tp.meta.full_name          # e.g. "music.Album"
    text = tp.as_text()
    metadata = {
        "schema": tp.meta.schema,
        "table": tp.meta.table,
        "row_count": tp.meta.row_count,
        "col_count": len(tp.meta.columns),
    }
    return doc_id, text, metadata


def index_all(
    force_reset: bool = False,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> int:
    """
    Profile and embed every table in every schema.

    Args:
        force_reset: if True, wipe ChromaDB before indexing (full re-index).
        progress_cb: optional callback(table_full_name, current, total).

    Returns:
        Number of tables indexed.
    """
    if force_reset:
        reset()

    print("Profiling all tables…")
    profiles = profile_all()
    total = len(profiles)
    print(f"Profiling complete. Embedding {total} tables into ChromaDB…\n")

    batch_size = 8
    indexed = 0

    for batch_start in range(0, total, batch_size):
        batch = profiles[batch_start : batch_start + batch_size]
        doc_ids, texts, metas = [], [], []
        embeddings = []

        for tp in batch:
            doc_id, text, meta = _profile_to_doc(tp)
            try:
                vec = embed_text(text)
                doc_ids.append(doc_id)
                texts.append(text)
                metas.append(meta)
                embeddings.append(vec)
                indexed += 1
                if progress_cb:
                    progress_cb(doc_id, indexed, total)
                else:
                    print(f"  [{indexed}/{total}] embedded {doc_id}")
            except Exception as e:
                print(f"  [warn] failed to embed {doc_id}: {e}")

        if doc_ids:
            upsert_batch(doc_ids, texts, embeddings, metas)

        # small pause between batches to avoid overwhelming Ollama
        if batch_start + batch_size < total:
            time.sleep(0.2)

    print(f"\nDone. {indexed}/{total} tables indexed. ChromaDB now holds {count()} documents.")
    return indexed


def index_table(schema: str, table: str) -> bool:
    """Embed and upsert a single table (used by the reindexer)."""
    try:
        tp = profile_table(schema, table)
        doc_id, text, meta = _profile_to_doc(tp)
        vec = embed_text(text)
        upsert_batch([doc_id], [text], [vec], [meta])
        return True
    except Exception as e:
        print(f"[error] Failed to index {schema}.{table}: {e}")
        return False


if __name__ == "__main__":
    index_all(force_reset=True)
