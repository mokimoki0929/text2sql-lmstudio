# src/groq_api.py
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, Optional, Tuple

import requests

from src.gpt_oss_local_api import _extract_content

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_TIMEOUT = 120


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """
    content がJSON以外を含んでいても、最初の { ... } を抜き出して parse する救済。
    """
    if not text:
        return None

    # そのままJSONとして読めるか
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # { ... } の塊を拾う（最短救済）
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None

    try:
        obj = json.loads(m.group(0))
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None

    return None


def _post_with_retry(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    *,
    timeout: int,
    max_retries: int = 3,
) -> requests.Response:
    """
    429/503/504 など一時エラーは軽くリトライ。
    """
    last_exc: Optional[Exception] = None
    for i in range(max_retries + 1):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code in (429, 503, 504):
                # Backoff（短め）
                sleep_s = min(2.0 * (2**i), 8.0)
                time.sleep(sleep_s)
                continue
            return r
        except Exception as e:
            last_exc = e
            sleep_s = min(1.0 * (2**i), 6.0)
            time.sleep(sleep_s)
            continue
    if last_exc:
        raise last_exc
    raise RuntimeError("request failed without exception")


def call_groq_text2sql(
    *,
    system: str,
    user: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
    temperature: float = 0.1,
    top_p: float = 0.95,
) -> Dict[str, Any]:
    """
    Groq OpenAI互換 /chat/completions を叩いて
    {"sql": "...", "assumptions": [...]} を返す。

    方針:
    1) json_schema を試す（対応モデルなら最強）
    2) 400で非対応なら json_object にフォールバック
    3) contentが壊れてても {..} 抽出で救済
    """
    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set")

    mdl = model or os.getenv("DEFAULT_GROQ_MODEL") or "llama-3.3-70b-versatile"

    url = f"{GROQ_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    # json_object時は「絶対JSONだけ返せ」をsystemで強化すると安定
    system_json_only = (
        system
        + "\n\n"
        + "Return ONLY a valid JSON object. No prose, no markdown, no code fences.\n"
        + 'The JSON must contain key "sql" (string) and optional "assumptions" (array of strings).\n'
        + "Do not include any other keys.\n"
    )

    base_payload = {
        "model": mdl,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "top_p": top_p,
    }

    # まず json_schema を試す
    payload_schema = {
        **base_payload,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "text_to_sql",
                # strict を強制すると非対応/失敗が増えるモデルがあるので False 推奨
                "strict": False,
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

    r = _post_with_retry(url, headers, payload_schema, timeout=timeout)

    # 400で json_schema 非対応なら json_object にフォールバック
    if r.status_code == 400 and "does not support response format `json_schema`" in r.text:
        payload_object = {
            **base_payload,
            "messages": [
                {"role": "system", "content": system_json_only},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        r = _post_with_retry(url, headers, payload_object, timeout=timeout)

    if r.status_code != 200:
        raise RuntimeError(f"Groq returned {r.status_code}: {r.text[:500]}")

    data = r.json()
    content = _extract_content(data)
    if not content:
        raise RuntimeError("Groq: no content in response")

    obj = _extract_json_object(content)
    if not obj or "sql" not in obj:
        raise RuntimeError("Groq: response is not valid JSON or missing 'sql'")

    # 余計なキーが来たら落とす（任意）
    out: Dict[str, Any] = {"sql": str(obj["sql"]).strip()}
    if "assumptions" in obj and isinstance(obj["assumptions"], list):
        out["assumptions"] = [str(x) for x in obj["assumptions"]]

    return out
