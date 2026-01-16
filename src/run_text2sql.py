# src/run_text2sql.py
from __future__ import annotations

import argparse
import json
import re
from typing import Any, Dict, List, Tuple, Optional

import psycopg
import sqlglot

from src.gpt_oss_local_api import get_config, _ensure_logger, _extract_content, ERROR_MESSAGE  # type: ignore
from src.text2sql_prompt import build_text2sql_messages

from src.groq_api import call_groq_text2sql

from dotenv import load_dotenv
load_dotenv()

FORBIDDEN_PATTERNS = [
    r";\s*\S",  # 複数ステートメントっぽい
    r"\b(insert|update|delete|merge|create|alter|drop|truncate|grant|revoke)\b",
    r"\b(begin|commit|rollback|savepoint)\b",
    r"\b(lock)\b",
    r"\bon\s+1\s*=\s*1\b",
    r"\bcross\s+join\b",
]


def _json_from_content(content: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(content)
    except Exception:
        return None


def guard_sql(sql: str, *, dialect: str = "postgres", max_limit: int = 100) -> str:
    """
    - SELECTのみ許可
    - 危険語や複数文を拒否
    - LIMITがなければ追加（max_limit）
    """
    s = sql.strip()
    if not s:
        raise ValueError("empty sql")

    # 軽い正規表現ガード（早期に落とす）
    lowered = s.lower()
    for pat in FORBIDDEN_PATTERNS:
        if re.search(pat, lowered):
            raise ValueError(f"forbidden pattern detected: {pat}")

    # sqlglotで構文解析し、SELECTのみを保証
    try:
        expr = sqlglot.parse_one(s, read=dialect)
    except Exception as e:
        raise ValueError(f"sql parse failed: {e}") from e

    if expr is None:
        raise ValueError("sql parse returned None")

    # Select 以外は拒否
    if expr.key != "select":
        raise ValueError(f"only SELECT is allowed, got: {expr.key}")

    # LIMITが無ければ付与 / あれば上限を絞る
    has_limit = expr.args.get("limit") is not None
    if not has_limit:
        s2 = s.rstrip().rstrip(";") + f" LIMIT {max_limit}"
        return s2

    # 既存LIMITが数値なら上限をmax_limitに丸める（非数値はそのまま）
    try:
        limit_expr = expr.args["limit"]
        limit_val = limit_expr.args.get("expression")
        if limit_val and limit_val.is_int:
            n = int(limit_val.this)
            if n > max_limit:
                s2 = re.sub(r"\blimit\s+\d+\b", f"LIMIT {max_limit}", s, flags=re.IGNORECASE)
                return s2
    except Exception:
        pass

    return s


def fetch_schema_summary(conn: psycopg.Connection, *, schema: str = "public") -> str:
    """
    information_schema からテーブル/カラムの概要だけ取ってプロンプトに入れる用。
    （本格的にやるなら型やPK/FKも入れるが、まずは軽量に）
    """
    q = """
    SELECT table_name, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = %s
    ORDER BY table_name, ordinal_position
    """
    rows = conn.execute(q, (schema,)).fetchall()

    # "TABLE x (...)" 形式に整形
    tables: Dict[str, List[Tuple[str, str]]] = {}
    for t, c, dt in rows:
        tables.setdefault(t, []).append((c, dt))

    lines: List[str] = ["-- schema introspected from information_schema"]
    for t, cols in tables.items():
        lines.append(f"TABLE {t} (")
        for c, dt in cols:
            lines.append(f"  {c} {dt},")
        lines.append(");")
        lines.append("")
    return "\n".join(lines).strip()


def call_lmstudio_text2sql(
    *,
    api_url: str,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.1,
    top_p: float = 0.95,
    timeout: int = 120,
) -> Dict[str, Any]:
    """
    LM Studio の /v1/chat/completions を叩いて structured JSON を受け取る。
    """
    import requests

    logger = _ensure_logger()

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "top_p": top_p,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "text_to_sql",
                "schema": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string"},
                        "assumptions": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["sql"],
                    "additionalProperties": False,
                },
            },
        },
    }

    logger.info("POST %s model=%s", api_url, model)
    res = requests.post(api_url, json=payload, timeout=timeout)
    if res.status_code != 200:
        logger.warning("non-200: %s", res.text[:500])
        raise RuntimeError(f"LM Studio returned {res.status_code}")

    data = res.json()
    content = _extract_content(data)
    if not content:
        raise RuntimeError("no content in response")

    obj = _json_from_content(content)
    if not obj or "sql" not in obj:
        raise RuntimeError("response is not valid JSON or missing 'sql'")

    return obj


def run_query(conn: psycopg.Connection, sql: str) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d.name for d in cur.description] if cur.description else []
        return cols, rows


def format_table(cols: List[str], rows: List[Tuple[Any, ...]], max_rows: int = 30) -> str:
    show = rows[:max_rows]
    col_widths = [len(c) for c in cols]
    for r in show:
        for i, v in enumerate(r):
            col_widths[i] = max(col_widths[i], len(str(v)))

    def fmt_row(vals):
        return " | ".join(str(v).ljust(col_widths[i]) for i, v in enumerate(vals))

    sep = "-+-".join("-" * w for w in col_widths)
    out = [fmt_row(cols), sep]
    for r in show:
        out.append(fmt_row(list(r)))

    if len(rows) > max_rows:
        out.append(f"... ({len(rows) - max_rows} more rows)")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Natural language -> SQL (LM Studio) -> Postgres execute")
    parser.add_argument("question", type=str, help="自然文の質問")
    parser.add_argument("--introspect", action="store_true", help="DBからスキーマを自動抽出してプロンプトに入れる")
    parser.add_argument("--max-limit", type=int, default=100, help="自動付与するLIMIT上限")
    parser.add_argument("--provider", type=str, default="lmstudio", choices=["lmstudio", "groq"])
    args = parser.parse_args()

    logger = _ensure_logger()

    cfg = get_config()
    api_url = cfg["api_url"]
    model = cfg.get("model", "openai/gpt-oss-20b")

    db = cfg.get("db") or {}
    host = db.get("host", "host.docker.internal")
    port = int(db.get("port", 5432))
    database = db.get("database", "appdb")
    user = db.get("user", "app")
    password = db.get("password", "app")
    dialect = db.get("dialect", "postgres")

    dsn = f"host={host} port={port} dbname={database} user={user} password={password}"

    logger.info("Connecting to Postgres: %s:%s/%s", host, port, database)
    with psycopg.connect(dsn) as conn:
        schema_text = None
        if args.introspect:
            schema_text = fetch_schema_summary(conn)

        bundle = build_text2sql_messages(
            args.question,
            dialect=dialect,
            schema=schema_text,
            max_limit=args.max_limit,
        )

        try:
            if args.provider == "groq":
                obj = call_groq_text2sql(
                    system=bundle.system,
                    user=bundle.user,
                    model=cfg.get("groq_model"),  # 任意
                    timeout=120,
                    temperature=0.1,
                    top_p=0.95,
                )
            else:
                obj = call_lmstudio_text2sql(
                    api_url=api_url,
                    model=model,
                    system=bundle.system,
                    user=bundle.user,
                    temperature=0.1,
                    top_p=0.95,
                    timeout=120,
                )
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            print(ERROR_MESSAGE)
            return

        sql_raw = str(obj.get("sql", "")).strip()
        assumptions = obj.get("assumptions") or []

        print("\n=== LLM Output (raw) ===")
        print(sql_raw)
        if assumptions:
            print("\n=== Assumptions ===")
            for a in assumptions:
                print(f"- {a}")

        try:
            sql_safe = guard_sql(sql_raw, dialect=dialect, max_limit=args.max_limit)
        except Exception as e:
            print("\n=== Guard Rejected SQL ===")
            print(f"Reason: {e}")
            return

        print("\n=== Executing SQL (guarded) ===")
        print(sql_safe)

        try:
            cols, rows = run_query(conn, sql_safe)
        except Exception as e:
            print("\n=== SQL Execution Error ===")
            print(str(e))
            return

        print("\n=== Result ===")
        if not cols:
            print("(no columns)")
            return
        print(format_table(cols, rows))


if __name__ == "__main__":
    main()