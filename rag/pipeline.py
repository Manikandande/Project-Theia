"""
RAG pipeline — the core of Theia's intelligence.

Flow:
  question
    → guardrail check (off-topic? reject immediately)
    → retriever (embed question → ChromaDB → top-k table descriptions)
    → prompt assembly (system prompt + context + question)
    → Ollama / Llama 3.1 8B
    → Theia's answer
"""

from __future__ import annotations

import requests

from config.settings import settings
from rag.retriever import retrieve_context_blocks
from security.guardrail import (
    OUT_OF_DOMAIN_RESPONSE,
    THEIA_SYSTEM_PROMPT,
    build_rag_prompt,
    is_likely_off_topic,
)


def _call_ollama(system: str, user: str) -> str:
    """Send a chat completion request to Ollama and stream the response."""
    resp = requests.post(
        f"{settings.ollama_base_url}/api/chat",
        json={
            "model": settings.llm_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "options": {
                "temperature": 0.2,   # low = more factual, less creative
                "top_p": 0.9,
                "num_predict": 1024,
            },
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def ask(question: str, top_k: int | None = None) -> dict:
    """
    Ask Theia a question. Returns a dict with:
      answer    — Theia's plain-English response
      sources   — list of table IDs used as context
      bypassed  — True if the guardrail blocked the question
    """
    if is_likely_off_topic(question):
        return {
            "answer": OUT_OF_DOMAIN_RESPONSE,
            "sources": [],
            "bypassed": True,
        }

    context_blocks = retrieve_context_blocks(question, top_k=top_k)
    user_prompt = build_rag_prompt(question, context_blocks)
    answer = _call_ollama(THEIA_SYSTEM_PROMPT, user_prompt)

    # Extract source table IDs from the retrieved documents
    # (first line of each block is "Table: schema.table")
    sources = []
    for block in context_blocks:
        first_line = block.split("\n")[0]
        if first_line.startswith("Table: "):
            sources.append(first_line.replace("Table: ", "").strip())

    return {
        "answer": answer,
        "sources": sources,
        "bypassed": False,
    }


if __name__ == "__main__":
    test_questions = [
        "What tables are in the music schema?",
        "What does the UnitPrice column in InvoiceLine mean?",
        "Who is the US president?",
    ]
    for q in test_questions:
        print(f"\nQ: {q}")
        print("-" * 60)
        result = ask(q)
        print(result["answer"])
        if result["sources"]:
            print(f"\n[Sources: {', '.join(result['sources'])}]")
