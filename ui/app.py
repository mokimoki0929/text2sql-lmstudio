# app.py
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import psycopg
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# -------------------------
# Streamlit
# -------------------------
st.set_page_config(page_title="Text2SQL Chat (LM Studio / Groq)", layout="wide")


# -------------------------
# Config
# -------------------------
def load_setting_json() -> Dict[str, Any]:
    """
    設定の探索順：
      1) 環境変数 CONFIG_JSON
      2) ./config/setting.json
    """
    candidates = []
    if os.getenv("CONFIG_JSON"):
        candidates.append(os.getenv("CONFIG_JSON"))
    candidates.append(os.path.join(os.getcwd(), "config", "setting.json"))

    tried = []
    for p in candidates:
        tried.append(p)
        if p and os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("setting.json not found. tried: " + " | ".join(tried))


def get_dsn(cfg: Dict[str, Any]) -> str:
    db = cfg.get("db") or {}
    host = db.get("host", "localhost")
    port = int(db.get("port", 5432))
    database = db.get("database", "appdb")
    user = db.get("user", "app")
    password = db.get("password", "app")
    return f"host={host} port={port} dbname={database} user={user} password={password}"


# -------------------------
# Data model (history)
# -------------------------
@dataclass
class UiTurn:
    question: str
    summary: Optional[str] = None
    sql: Optional[str] = None
    cols: Optional[List[str]] = None
    rows: Optional[List[List[Any]]] = None
    error: Optional[str] = None


# -------------------------
# DB schema summary
# -------------------------
def fetch_schema_summary(conn: psycopg.Connection, max_tables: int = 80) -> str:
    q_tables = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_schema NOT IN ('pg_catalog','information_schema')
      AND table_type='BASE TABLE'
    ORDER BY table_schema, table_name
    LIMIT %s;
    """
    q_cols = """
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema=%s AND table_name=%s
    ORDER BY ordinal_position;
    """
    out: List[str] = []
    with conn.cursor() as cur:
        cur.execute(q_tables, (max_tables,))
        tables = cur.fetchall()
        for schema, table in tables:
            out.append(f"- {schema}.{table}")
            cur.execute(q_cols, (schema, table))
            cols = cur.fetchall()
            for col_name, data_type in cols:
                out.append(f"  - {col_name}: {data_type}")
    return "\n".join(out)


def run_query(conn: psycopg.Connection, sql: str, max_rows: int = 300) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    with conn.cursor() as cur:
        cur.execute(sql)
        if cur.description is None:
            return [], []
        cols = [d.name for d in cur.description]
        rows = cur.fetchmany(max_rows)
        return cols, rows


# -------------------------
# SQL guard
# -------------------------
FORBIDDEN_PATTERNS = [
    r";\s*\S",  # 2文以上っぽい
    r"\b(insert|update|delete|merge|create|alter|drop|truncate|grant|revoke)\b",
    r"\b(begin|commit|rollback|savepoint)\b",
    r"\b(lock)\b",
    r"\bon\s+1\s*=\s*1\b",
    r"\bcross\s+join\b",
]


def guard_sql(sql: str, max_limit: int = 100) -> str:
    s = (sql or "").strip()
    if not s:
        raise ValueError("SQLが空です")

    # \n が文字として混ざる問題を潰す
    s = s.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r").strip()

    head = s.lstrip().lower()
    if not (head.startswith("select") or head.startswith("with")):
        raise ValueError("SELECT/WITH以外のSQLは拒否します")

    low = s.lower()
    for pat in FORBIDDEN_PATTERNS:
        if re.search(pat, low, flags=re.IGNORECASE):
            raise ValueError(f"危険なSQLパターンを検出したため拒否しました: {pat}")

    # LIMITの付与/丸め
    m = re.search(r"\blimit\s+(\d+)\b", low)
    if m:
        lim = int(m.group(1))
        if lim > max_limit:
            s = re.sub(r"\blimit\s+\d+\b", f"LIMIT {max_limit}", s, flags=re.IGNORECASE)
    else:
        s = s.rstrip().rstrip(";") + f" LIMIT {max_limit}"

    return s


# -------------------------
# LLM calls: LM Studio / Groq
# -------------------------
def lmstudio_chat(cfg: Dict[str, Any], messages: List[Dict[str, str]], temperature: float = 0.1) -> str:
    url = cfg.get("api_url")
    model = cfg.get("model")
    if not url or not model:
        raise RuntimeError("setting.json の api_url / model が未設定です")

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": 0.95,
        # response_format は送らない（LM Studio制約回避）
    }
    r = requests.post(url, json=payload, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"LM Studio returned {r.status_code}: {r.text[:500]}")
    data = r.json()
    return data["choices"][0]["message"]["content"]


def groq_chat(messages: List[Dict[str, str]], temperature: float = 0.1) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY が .env にありません")
    url = "https://api.groq.com/openai/v1/chat/completions"

    model = os.getenv("DEFAULT_GROQ_MODEL", "llama-3.3-70b-versatile")
    payload = {"model": model, "messages": messages, "temperature": temperature, "top_p": 0.95}
    headers = {"Authorization": f"Bearer {api_key}"}

    r = requests.post(url, json=payload, headers=headers, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Groq returned {r.status_code}: {r.text[:500]}")
    data = r.json()
    return data["choices"][0]["message"]["content"]


def extract_sql_from_text(text: str) -> str:
    # 1) JSONが返ってきたら {sql: "..."} を拾う
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "sql" in obj and isinstance(obj["sql"], str):
            return obj["sql"].strip()
    except Exception:
        pass

    # 2) ```sql ... ``` を優先
    m = re.search(r"```sql\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # 3) 最初の SELECT/WITH から最後まで（余計な説明がある場合は;で切る）
    m = re.search(r"\b(with|select)\b.*", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        sql = m.group(0).strip()
        if ";" in sql:
            sql = sql.split(";", 1)[0].strip()
        return sql

    raise RuntimeError("LLMの応答からSQLを抽出できませんでした")


def build_text2sql_prompt(schema_text: Optional[str], question: str) -> Tuple[str, str]:
    """
    system / user を返す
    """
    schema_part = schema_text or "(schema unavailable)"
    system = (
        "あなたはPostgreSQLのSQLエキスパートです。"
        "ユーザーの質問に対して、安全なSELECT/CTE（WITH）のみを生成してください。"
        "INSERT/UPDATE/DELETE/DDLは禁止です。"
        "必ず実行可能なSQLだけを返してください。余計な説明は禁止です。"
    )

    user = f"""以下のDBスキーマを参照してSQLを1つだけ作ってください。

[Schema]
{schema_part}

[Rules]
- 返すのはSQLのみ（説明文なし）
- SELECT または WITH で始める
- 必要ならテーブル結合する
- 取りすぎないように LIMIT 100 を付ける（無ければ後で付ける）

[Question]
{question}
"""
    return system, user


def call_text2sql(provider: str, cfg: Dict[str, Any], schema_text: Optional[str], question: str) -> str:
    system, user = build_text2sql_prompt(schema_text, question)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    if provider == "groq":
        out = groq_chat(msgs, temperature=0.1)
    else:
        out = lmstudio_chat(cfg, msgs, temperature=0.1)

    return extract_sql_from_text(out)


def call_summary(provider: str, cfg: Dict[str, Any], question: str, sql: str, df: pd.DataFrame) -> str:
    # 結果を縮める
    head = df.head(15).to_dict(orient="records")
    profile = {"rows": int(df.shape[0]), "cols": list(df.columns)}

    prompt = f"""あなたはデータ分析アシスタントです。
次の「質問」「SQL」「結果」をもとに、日本語で短い要約（3〜6行）を書いてください。
- 推測しない
- 数字があるなら具体的に書く
- 最後に「次に見ると良い指標」を1つ提案（1行）

[質問]
{question}

[SQL]
{sql}

[結果概要]
{json.dumps(profile, ensure_ascii=False, default=str)}

[結果サンプル]
{json.dumps(head, ensure_ascii=False, default=str)}
"""

    msgs = [{"role": "user", "content": prompt}]
    if provider == "groq":
        return groq_chat(msgs, temperature=0.3)
    return lmstudio_chat(cfg, msgs, temperature=0.3)


# -------------------------
# Visualization
# -------------------------
def render_result(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        st.info("結果が0件でした")
        return

    # 1) 1行1列はKPIカード
    if df.shape[0] == 1 and df.shape[1] == 1:
        st.metric(label=str(df.columns[0]), value=str(df.iloc[0, 0]))
        return

    # 2) 一覧系は表（id + created_at など）
    id_like = {"customer_id", "product_id", "order_id", "order_item_id"}
    has_id = any(c in df.columns for c in id_like)
    has_created = any(c in df.columns for c in ["created_at", "updated_at"])
    if has_id and has_created:
        st.dataframe(df, use_container_width=True)
        return

    obj_cols = [c for c in df.columns if df[c].dtype == object]
    if len(obj_cols) >= 2 and df.shape[1] >= 3:
        st.dataframe(df, use_container_width=True)
        return

    # 3) 時系列: datetime列 + 数値列
    dt_col: Optional[str] = None
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            dt_col = c
            break

    if dt_col is None:
        for c in df.columns:
            if df[c].dtype == object:
                try:
                    tmp = pd.to_datetime(df[c], errors="raise")
                    df = df.copy()
                    df[c] = tmp
                    dt_col = c
                    break
                except Exception:
                    pass

    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

    if dt_col and num_cols:
        df2 = df[[dt_col] + num_cols].dropna(subset=[dt_col]).sort_values(dt_col)
        df2 = df2.set_index(dt_col)
        st.line_chart(df2)
        return

    # 4) カテゴリ + 数値: 棒（上位20）
    if len(df.columns) >= 2:
        # 数値列
        num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        if not num_cols:
            st.dataframe(df, use_container_width=True)
            return

        # ★IDっぽい列はY候補から除外（customer_id, product_id, ...）
        id_like = {"customer_id", "product_id", "order_id", "order_item_id"}
        y_candidates = [c for c in num_cols if c not in id_like and not c.lower().endswith("_id")]

        # ★指標っぽい列名を優先（count/sales/total/qty/amount/rate）
        priority = ["count", "cnt", "num", "sales", "revenue", "total", "sum", "qty", "quantity", "amount", "avg", "rate", "ratio"]
        def score(col: str) -> int:
            name = col.lower()
            s = 0
            for i, key in enumerate(priority):
                if key in name:
                    s += 100 - i  # 早いほど高得点
            return s

        if y_candidates:
            y_col = sorted(y_candidates, key=score, reverse=True)[0]
        else:
            # 指標が全部IDしか無いなら仕方なく最初の数値列
            y_col = num_cols[0]

        # ★X（カテゴリ）は文字列優先、無ければID列を使う
        cat_col = next((c for c in df.columns if df[c].dtype == object), None)
        if cat_col is None:
            # ID列があればそれをXに
            cat_col = next((c for c in df.columns if c in id_like or c.lower().endswith("_id")), df.columns[0])

        df2 = df[[cat_col, y_col]].copy()
        df2[cat_col] = df2[cat_col].astype(str)
        df2 = df2.dropna(subset=[y_col]).set_index(cat_col)

        # 件数が多すぎると見づらいので上位20
        if df2.shape[0] > 20:
            df2 = df2.sort_values(by=y_col, ascending=False).head(20)

        st.bar_chart(df2)
        return


# -------------------------
# App
# -------------------------
def main() -> None:
    cfg = load_setting_json()
    dsn = get_dsn(cfg)

    st.title("Text2SQL Chat (LM Studio / Groq)")

    if "turns" not in st.session_state:
        st.session_state["turns"] = []  # List[UiTurn]

    # schema cache
    if "schema_text" not in st.session_state:
        try:
            with psycopg.connect(dsn) as conn:
                st.session_state["schema_text"] = fetch_schema_summary(conn)
        except Exception as e:
            st.session_state["schema_text"] = None
            st.warning(f"スキーマ取得に失敗（続行）: {e}")

    # Sidebar
    with st.sidebar:
        st.header("分析を選択")
        provider = st.selectbox("LLM Provider", ["lmstudio", "groq"], index=0)

        st.caption("ボタンを押すと質問が入力されます")
        presets = [
            ("売上合計（先月）", "先月のpaidの売上合計を教えて"),
            ("売上合計（今月）", "今月のpaidの売上合計を教えて"),
            ("カテゴリ別売上（60日）", "直近60日間のカテゴリ別売上（paid）を出して"),
            ("日別売上（14日）", "直近14日間の日別売上（paid）を日付昇順で出して"),
            ("顧客別売上（60日）", "直近60日間の顧客別売上（paid）を出して（上位20）"),
            ("キャンセル率（30日）", "直近30日間のキャンセル率（cancelled件数/全注文件数）を小数で出して"),
            ("未注文顧客（上位100）", "注文が一度もない顧客を出して（customer_idとnameだけ）"),
        ]
        if "draft" not in st.session_state:
            st.session_state["draft"] = ""
        for label, q in presets:
            if st.button(label, use_container_width=True):
                st.session_state["draft"] = q

        st.divider()
        st.caption("Tips: スキーマを読んでから生成すると精度が上がります（起動時に自動取得）。")

    # Render history (always)
    for t in st.session_state["turns"]:
        with st.chat_message("user"):
            st.markdown(t.question)
        with st.chat_message("assistant"):
            if t.error:
                st.error(t.error)
                continue
            if t.summary:
                st.markdown(t.summary)
            if t.sql:
                st.code(t.sql, language="sql")
            if t.cols is not None and t.rows is not None:
                df = pd.DataFrame(t.rows, columns=t.cols)
                render_result(df)

    # Input
    question = st.chat_input("質問を入力してください")
    if not question and st.session_state.get("draft"):
        question = st.session_state["draft"]
        st.session_state["draft"] = ""

    if not question:
        return

    # New turn: display "question" immediately; show answer after generated
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        status = st.empty()
        status.info("SQL生成→実行→要約生成中...")

        turn = UiTurn(question=question)

        try:
            sql_raw = call_text2sql(provider, cfg, st.session_state.get("schema_text"), question)
            sql_safe = guard_sql(sql_raw, max_limit=100)
            turn.sql = sql_safe

            with psycopg.connect(dsn) as conn:
                cols, rows = run_query(conn, sql_safe, max_rows=300)

            turn.cols = cols
            turn.rows = [list(r) for r in rows]

            df = pd.DataFrame(turn.rows, columns=turn.cols)

            # Summary
            turn.summary = call_summary(provider, cfg, question, turn.sql, df)

            status.empty()
            if turn.summary:
                st.markdown(turn.summary)
            st.code(turn.sql, language="sql")
            render_result(df)

        except Exception as e:
            turn.error = str(e)
            status.empty()
            st.error(turn.error)

    # Save to history
    st.session_state["turns"].append(turn)


if __name__ == "__main__":
    main()
