"""
ChromaDB wrapper — persistent local vector store.

All table embeddings are stored in a single collection ("theia_schema").
Each document is the profiled text description of one table.
The document ID is "{schema}.{table}" so upserts are idempotent.
"""

from __future__ import annotations

import chromadb
from chromadb.config import Settings as ChromaSettings

from config.settings import settings


_client: chromadb.ClientAPI | None = None
_COLLECTION_NAME = "theia_schema"


def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=str(settings.chroma_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def get_collection() -> chromadb.Collection:
    client = _get_client()
    return client.get_or_create_collection(
        name=_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def upsert(
    doc_id: str,
    text: str,
    embedding: list[float],
    metadata: dict | None = None,
) -> None:
    """Add or update a single document in the store."""
    col = get_collection()
    col.upsert(
        ids=[doc_id],
        documents=[text],
        embeddings=[embedding],
        metadatas=[metadata or {}],
    )


def upsert_batch(
    doc_ids: list[str],
    texts: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict] | None = None,
) -> None:
    """Batch upsert — more efficient than calling upsert() in a loop."""
    col = get_collection()
    col.upsert(
        ids=doc_ids,
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas or [{} for _ in doc_ids],
    )


def search(
    query_embedding: list[float],
    top_k: int | None = None,
) -> list[dict]:
    """
    Return the top_k most similar documents.

    Each result dict contains:
      id, document (the stored text), metadata, distance
    """
    k = top_k or settings.retriever_top_k
    col = get_collection()
    results = col.query(
        query_embeddings=[query_embedding],
        n_results=min(k, col.count() or 1),
        include=["documents", "metadatas", "distances"],
    )
    output = []
    for i, doc_id in enumerate(results["ids"][0]):
        output.append({
            "id": doc_id,
            "document": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i],
        })
    return output


def count() -> int:
    return get_collection().count()


def reset() -> None:
    """Delete the collection if it exists (used during full re-indexing)."""
    client = _get_client()
    try:
        client.delete_collection(_COLLECTION_NAME)
    except Exception:
        pass
