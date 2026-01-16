# src/text2sql_prompt.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional


DEFAULT_SCHEMA = """\
-- PostgreSQL schema (public)
TABLE customers (
  customer_id serial primary key,
  name text not null,
  email text unique not null,
  created_at timestamp not null
);

TABLE products (
  product_id serial primary key,
  name text not null,
  category text not null,
  price_jpy integer not null,
  is_active boolean not null
);

TABLE orders (
  order_id serial primary key,
  customer_id integer not null references customers(customer_id),
  order_date date not null,
  status text not null, -- one of: placed, paid, shipped, cancelled
  total_jpy integer not null
);

TABLE order_items (
  order_item_id serial primary key,
  order_id integer not null references orders(order_id),
  product_id integer not null references products(product_id),
  quantity integer not null,
  unit_price_jpy integer not null
);

-- Notes:
-- orders.total_jpy is the order total.
-- order_items has line items; join order_items->orders and order_items->products when needed.
"""


@dataclass(frozen=True)
class PromptBundle:
    system: str
    user: str


def build_text2sql_messages(
    question: str,
    *,
    dialect: str = "postgres",
    schema: Optional[str] = None,
    max_limit: int = 100,
    now_tz: str = "Asia/Tokyo",
) -> PromptBundle:
    """
    Text-to-SQL 用の system/user メッセージを作る。
    LM Studio には OpenAI互換の chat/completions と structured output を使わせる想定。
    """
    schema_text = schema or DEFAULT_SCHEMA

    now = datetime.now(ZoneInfo(now_tz))
    today = now.date().isoformat()

    system = f"""\
You are a careful Text-to-SQL assistant for {dialect}.
Follow ALL rules:

[Hard rules]
- Output must be valid JSON matching the given schema (handled by response_format).
- Generate exactly ONE SQL statement.
- Only SELECT is allowed. Never use INSERT/UPDATE/DELETE/MERGE/DDL.
- Never use transactions, locks, or PRAGMA.
- Use only the tables/columns that exist in the schema.
- If the question is ambiguous, still produce the best SELECT and list assumptions.

[Safety & performance]
- Always include LIMIT {max_limit} unless user explicitly asks for fewer.
- Prefer simple queries; avoid heavy CROSS JOINs.
- Dates: interpret relative expressions using TODAY = {today}.

[Answer style]
- Do not explain. The JSON will contain "sql" and optional "assumptions".
"""

    user = f"""\
[Schema]
{schema_text}

[Question]
{question}
"""
    return PromptBundle(system=system, user=user)