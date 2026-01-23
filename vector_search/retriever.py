from __future__ import annotations

from typing import Any, Dict, List

import psycopg

from vector_search.embedding import embed_texts
from vector_search.store import search


def retrieve(
    conn: psycopg.Connection,
    cfg: Dict[str, Any],
    question: str,
    *,
    top_k: int | None = None,
    filters: Dict[str, str] | None = None,
    min_score: float | None = None,
) -> List[Dict[str, Any]]:
    if top_k is None:
        top_k = int(cfg.get("rag_top_k", 4))
    embeddings = embed_texts(cfg, [question])
    return search(conn, embeddings[0], top_k, filters=filters, min_score=min_score)
