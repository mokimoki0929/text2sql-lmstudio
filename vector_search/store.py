from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

import psycopg
from psycopg.types.json import Json
from psycopg import sql

from vector_search.types import VectorDoc


def _vector_literal(vec: Iterable[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


def ensure_vector_schema(conn: psycopg.Connection, dim: int) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS vector_docs (
              id bigserial PRIMARY KEY,
              source text NOT NULL,
              text text NOT NULL,
              metadata jsonb,
              embedding vector({dim}) NOT NULL
            )
            """
        )
    conn.commit()


def reset_index(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE vector_docs")
    conn.commit()


def insert_docs(conn: psycopg.Connection, docs: List[VectorDoc], embeddings: List[List[float]]) -> None:
    if not docs:
        return
    if len(docs) != len(embeddings):
        raise ValueError("docs and embeddings length mismatch")

    rows: List[Tuple[Any, ...]] = []
    for doc, emb in zip(docs, embeddings):
        rows.append((doc.source, doc.text, Json(doc.metadata), _vector_literal(emb)))

    sql = """
    INSERT INTO vector_docs (source, text, metadata, embedding)
    VALUES (%s, %s, %s, %s::vector)
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()


def search(
    conn: psycopg.Connection,
    query_emb: List[float],
    top_k: int,
    filters: Dict[str, str] | None = None,
    min_score: float | None = None,
) -> List[Dict[str, Any]]:
    lit = _vector_literal(query_emb)
    where_parts = [sql.SQL("1=1")]
    params: List[Any] = [lit]

    if filters:
        for key, value in filters.items():
            where_parts.append(sql.SQL("metadata ->> %s = %s"))
            params.extend([key, value])

    if min_score is not None:
        where_parts.append(sql.SQL("(1 - (embedding <=> %s::vector)) >= %s"))
        params.extend([lit, float(min_score)])

    params.extend([lit, top_k])
    stmt = sql.SQL(
        """
        SELECT source, text, metadata, 1 - (embedding <=> %s::vector) AS score
        FROM vector_docs
        WHERE {where_clause}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """
    ).format(where_clause=sql.SQL(" AND ").join(where_parts))

    with conn.cursor() as cur:
        cur.execute(stmt, params)
        rows = cur.fetchall()

    out: List[Dict[str, Any]] = []
    for source, text, metadata, score in rows:
        out.append(
            {
                "source": source,
                "text": text,
                "metadata": metadata,
                "score": float(score),
            }
        )
    return out
