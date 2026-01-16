from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Tuple

import psycopg

from src.run_text2sql import (
    call_lmstudio_text2sql,
    fetch_schema_summary,
    format_table,
    guard_sql,
    run_query,
)
from src.text2sql_prompt import build_text2sql_messages
from src.gpt_oss_local_api import get_config, _ensure_logger

from src.groq_api import call_groq_text2sql

from dotenv import load_dotenv
load_dotenv()

@dataclass
class CaseResult:
    id: int
    ok_exec: bool
    ok_match: bool
    guard_rejected: bool
    error: str | None = None


def _to_decimal(x: Any) -> Decimal | None:
    if x is None:
        return None
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        # floatは文字列経由で誤差を抑える。例外は握りつぶす
        try:
            return Decimal(str(x))
        except Exception:
            return None
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return None
        # 数値っぽい文字列だけ許可（例: -12, 3.14, 1e-5）
        import re
        if not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", s):
            return None
        try:
            return Decimal(s)
        except Exception:
            return None
    return None


def normalize_value(x: Any, *, float_round: int = 6) -> Any:
    """
    値を比較しやすい形に正規化
    - 数値っぽいものはDecimalにして丸め
    - 文字列はtrim & 空はNone
    - bool/intはそのまま
    """
    if x is None:
        return None

    if isinstance(x, str):
        s = x.strip()
        return None if s == "" else s

    d = _to_decimal(x)
    if d is not None:
        # 小数は丸めて比較
        q = Decimal("1." + ("0" * float_round))
        return d.quantize(q)

    return x


def normalize_rows(
    rows: List[Tuple[Any, ...]],
    *,
    float_round: int = 6,
    ignore_row_order: bool = True,
) -> List[Tuple[Any, ...]]:
    norm = []
    for r in rows:
        norm.append(tuple(normalize_value(v, float_round=float_round) for v in r))

    if ignore_row_order:
        # 行順無視：ソートして比較
        norm.sort(key=lambda t: tuple("" if v is None else str(v) for v in t))

    return norm


def is_single_scalar(rows: List[Tuple[Any, ...]]) -> bool:
    return len(rows) == 1 and len(rows[0]) == 1


def compare_lenient(
    expected_rows: List[Tuple[Any, ...]],
    actual_rows: List[Tuple[Any, ...]],
    *,
    float_round: int = 6,
) -> bool:
    """
    ゆるめ比較
    - 列名/列順は無視（= rowsだけ比較）
    - 行順は無視
    - 数値は丸めて比較
    - 1x1の集計は scalar一致ならOK
    """
    exp_n = normalize_rows(expected_rows, float_round=float_round, ignore_row_order=True)
    act_n = normalize_rows(actual_rows, float_round=float_round, ignore_row_order=True)

    # 1x1なら厳密にその値比較だけ
    if is_single_scalar(exp_n) and is_single_scalar(act_n):
        return exp_n[0][0] == act_n[0][0]

    # 行数・列数が違うなら基本不一致（ここはまだ“ゆるめ”の範囲）
    # もっと緩めたいなら「列数が違っても共通部分だけ比較」も可能
    if len(exp_n) != len(act_n):
        return False
    if exp_n and act_n and (len(exp_n[0]) != len(act_n[0])):
        return False

    return exp_n == act_n


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=str, default="eval/questions_ja.jsonl")
    parser.add_argument("--introspect", action="store_true")
    parser.add_argument("--max-limit", type=int, default=100)
    parser.add_argument("--float-round", type=int, default=6, help="数値の丸め桁（小数）")
    parser.add_argument("--show-mismatch", action="store_true", help="不一致ケースの詳細を表示")
    parser.add_argument("--provider", type=str, default="lmstudio", choices=["lmstudio", "groq"])
    args = parser.parse_args()

    logger = _ensure_logger()
    cfg = get_config()

    api_url = cfg["api_url"]
    model = cfg.get("model", "openai/gpt-oss-20b")

    db = cfg.get("db") or {}
    host = db.get("host", "localhost")
    port = int(db.get("port", 5432))
    database = db.get("database", "appdb")
    user = db.get("user", "app")
    password = db.get("password", "app")
    dialect = db.get("dialect", "postgres")
    dsn = f"host={host} port={port} dbname={database} user={user} password={password}"

    cases: List[Dict[str, Any]] = []
    with open(args.questions, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))

    results: List[CaseResult] = []
    with psycopg.connect(dsn) as conn:
        schema_text = fetch_schema_summary(conn) if args.introspect else None

        for case in cases:
            cid = int(case["id"])
            question = str(case["question"])
            ref_sql = str(case["reference_sql"])

            logger.info("CASE %s: %s", cid, question)

            # 参照SQL（正解）
            try:
                ref_cols, ref_rows = run_query(conn, ref_sql)
            except Exception as e:
                results.append(
                    CaseResult(cid, ok_exec=False, ok_match=False, guard_rejected=False, error=f"ref_sql error: {e}")
                )
                continue

            bundle = build_text2sql_messages(
                question,
                dialect=dialect,
                schema=schema_text,
                max_limit=args.max_limit,
            )

            # LLM SQL生成
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
                sql_raw = str(obj.get("sql", "")).strip()
            except Exception as e:
                results.append(
                    CaseResult(cid, ok_exec=False, ok_match=False, guard_rejected=False, error=f"lmstudio error: {e}")
                )
                continue

            # ガード
            try:
                sql_safe = guard_sql(sql_raw, dialect=dialect, max_limit=args.max_limit)
            except Exception as e:
                results.append(CaseResult(cid, ok_exec=False, ok_match=False, guard_rejected=True, error=f"guard: {e}"))
                continue

            # 実行
            try:
                out_cols, out_rows = run_query(conn, sql_safe)
            except Exception as e:
                results.append(CaseResult(cid, ok_exec=False, ok_match=False, guard_rejected=False, error=f"exec: {e}"))
                continue

            ok_match = compare_lenient(ref_rows, out_rows, float_round=args.float_round)
            results.append(CaseResult(cid, ok_exec=True, ok_match=ok_match, guard_rejected=False, error=None))

            if args.show_mismatch and not ok_match:
                print("\n--- MISMATCH CASE", cid, "---")
                print("Q:", question)
                print("\n[LLM SQL]\n", sql_safe)
                print("\n[Expected SQL]\n", ref_sql)
                print("\n[LLM Result]")
                print(format_table(out_cols, out_rows))
                print("\n[Expected Result]")
                print(format_table(ref_cols, ref_rows))

    total = len(results)
    exec_ok = sum(1 for r in results if r.ok_exec)
    match_ok = sum(1 for r in results if r.ok_match)
    guard_ng = sum(1 for r in results if r.guard_rejected)

    print("\n=== SUMMARY (LENIENT) ===")
    print(f"cases: {total}")
    print(f"exec_success: {exec_ok}/{total} = {exec_ok/total:.3f}")
    print(f"lenient_result_match: {match_ok}/{total} = {match_ok/total:.3f}")
    print(f"guard_rejected: {guard_ng}/{total} = {guard_ng/total:.3f}")

    fails = [r for r in results if not r.ok_match]
    if fails:
        print("\n=== FAIL CASES ===")
        for r in fails:
            print(f"- id={r.id} exec={r.ok_exec} match={r.ok_match} guard={r.guard_rejected} err={r.error}")


if __name__ == "__main__":
    main()