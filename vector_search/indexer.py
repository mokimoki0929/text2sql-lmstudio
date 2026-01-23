from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import psycopg
from psycopg import sql

from vector_search.embedding import embed_texts
from vector_search.store import ensure_vector_schema, insert_docs, reset_index
from vector_search.types import VectorDoc


def _collect_tables(conn: psycopg.Connection, max_tables: int) -> List[Dict[str, str]]:
    q = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
      AND table_type = 'BASE TABLE'
    ORDER BY table_schema, table_name
    LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(q, (max_tables,))
        return [{"schema": s, "table": t} for s, t in cur.fetchall()]


def _collect_columns(conn: psycopg.Connection, schema: str, table: str) -> List[Dict[str, str]]:
    q = """
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = %s AND table_name = %s
    ORDER BY ordinal_position
    """
    with conn.cursor() as cur:
        cur.execute(q, (schema, table))
        return [{"name": c, "type": t} for c, t in cur.fetchall()]


def _pick_column(cols: List[Dict[str, str]], candidates: List[str]) -> Optional[Dict[str, str]]:
    lower_map = {c["name"].lower(): c for c in cols}
    for name in candidates:
        if name in lower_map:
            return lower_map[name]
    for c in cols:
        cname = c["name"].lower()
        for name in candidates:
            if cname.endswith(name):
                return c
    return None


def _is_numeric_type(data_type: str) -> bool:
    t = data_type.lower()
    return any(
        key in t
        for key in [
            "int",
            "numeric",
            "decimal",
            "real",
            "double",
            "float",
            "money",
        ]
    )


def _collect_snapshots(
    conn: psycopg.Connection,
    schema: str,
    table: str,
    cols: List[Dict[str, str]],
    months: int,
    max_rows: int,
) -> List[VectorDoc]:
    date_col = _pick_column(cols, ["order_date", "created_at", "date"])
    if not date_col:
        return []

    amount_col = None
    for c in cols:
        if _is_numeric_type(c["type"]):
            if any(
                key in c["name"].lower()
                for key in ["total", "amount", "sales", "revenue", "price", "sum"]
            ):
                amount_col = c
                break

    if not amount_col:
        return []

    status_col = _pick_column(cols, ["status", "state", "is_active"])

    docs: List[VectorDoc] = []
    if status_col:
        query = sql.SQL(
            """
            SELECT date_trunc('month', {dt})::date AS month,
                   {status}::text AS status,
                   SUM({amount}) AS total,
                   COUNT(*) AS cnt
            FROM {schema}.{table}
            WHERE {dt} >= (CURRENT_DATE - (%s || ' months')::interval)
            GROUP BY 1, 2
            ORDER BY 1 DESC
            LIMIT %s
            """
        ).format(
            dt=sql.Identifier(date_col["name"]),
            status=sql.Identifier(status_col["name"]),
            amount=sql.Identifier(amount_col["name"]),
            schema=sql.Identifier(schema),
            table=sql.Identifier(table),
        )
        params = (months, max_rows)
    else:
        query = sql.SQL(
            """
            SELECT date_trunc('month', {dt})::date AS month,
                   SUM({amount}) AS total,
                   COUNT(*) AS cnt
            FROM {schema}.{table}
            WHERE {dt} >= (CURRENT_DATE - (%s || ' months')::interval)
            GROUP BY 1
            ORDER BY 1 DESC
            LIMIT %s
            """
        ).format(
            dt=sql.Identifier(date_col["name"]),
            amount=sql.Identifier(amount_col["name"]),
            schema=sql.Identifier(schema),
            table=sql.Identifier(table),
        )
        params = (months, max_rows)

    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    except Exception:
        return []

    for row in rows:
        if status_col:
            month, status, total, cnt = row
            meta = {
                "schema": schema,
                "table": table,
                "type": "snapshot",
                "month": str(month),
                "status": str(status),
            }
            text = (
                f"SNAPSHOT {schema}.{table}: month={month} status={status} "
                f"total={total} count={cnt}"
            )
        else:
            month, total, cnt = row
            meta = {
                "schema": schema,
                "table": table,
                "type": "snapshot",
                "month": str(month),
            }
            text = (
                f"SNAPSHOT {schema}.{table}: month={month} total={total} count={cnt}"
            )
        docs.append(VectorDoc(source=f"snapshot:{schema}.{table}", text=text, metadata=meta))

    return docs


def _collect_sample_rows(
    conn: psycopg.Connection, schema: str, table: str, limit: int
) -> List[Dict[str, Any]]:
    if limit <= 0:
        return []
    query = sql.SQL("SELECT * FROM {}.{} LIMIT %s").format(
        sql.Identifier(schema), sql.Identifier(table)
    )
    with conn.cursor() as cur:
        cur.execute(query, (limit,))
        rows = cur.fetchall()
        cols = [d.name for d in cur.description] if cur.description else []
    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append(dict(zip(cols, row)))
    return out


def collect_docs(
    conn: psycopg.Connection,
    *,
    max_tables: int = 80,
    sample_rows_per_table: int = 3,
    snapshot_months: int = 6,
    snapshot_max_rows: int = 24,
) -> List[VectorDoc]:
    docs: List[VectorDoc] = []
    tables = _collect_tables(conn, max_tables=max_tables)
    for item in tables:
        schema = item["schema"]
        table = item["table"]
        cols = _collect_columns(conn, schema, table)
        col_desc = ", ".join(f"{c['name']} {c['type']}" for c in cols)
        text = f"TABLE {schema}.{table}: columns {col_desc}"
        docs.append(
            VectorDoc(
                source=f"schema:{schema}.{table}",
                text=text,
                metadata={"schema": schema, "table": table, "type": "table"},
            )
        )

        docs.extend(
            _collect_snapshots(
                conn,
                schema,
                table,
                cols,
                months=snapshot_months,
                max_rows=snapshot_max_rows,
            )
        )

        samples = _collect_sample_rows(conn, schema, table, sample_rows_per_table)
        for i, row in enumerate(samples):
            row_text = json.dumps(row, ensure_ascii=True, default=str)
            row_meta = {k: str(v) for k, v in row.items()}
            row_meta.update({"schema": schema, "table": table, "type": "row"})
            docs.append(
                VectorDoc(
                    source=f"row:{schema}.{table}#{i}",
                    text=f"ROW {schema}.{table}: {row_text}",
                    metadata=row_meta,
                )
            )
    return docs


def build_index(
    conn: psycopg.Connection,
    cfg: Dict[str, Any],
    *,
    reset: bool = True,
    max_tables: int = 80,
    sample_rows_per_table: int = 3,
    snapshot_months: int = 6,
    snapshot_max_rows: int = 24,
) -> int:
    docs = collect_docs(
        conn,
        max_tables=max_tables,
        sample_rows_per_table=sample_rows_per_table,
        snapshot_months=snapshot_months,
        snapshot_max_rows=snapshot_max_rows,
    )
    if not docs:
        return 0

    embeddings = embed_texts(cfg, [d.text for d in docs])
    dim = len(embeddings[0])
    ensure_vector_schema(conn, dim)
    if reset:
        reset_index(conn)
    insert_docs(conn, docs, embeddings)
    return len(docs)
