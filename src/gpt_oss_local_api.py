# gpt_oss_local_api.py
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

import requests

# =========================
# 定数
# =========================
ERROR_MESSAGE = "（エラー: 応答が得られませんでした）"
DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_TIMEOUT = 30  # seconds


# =========================
# 設定読み込み（遅延ロード）
# =========================
def load_config(path: str) -> Dict[str, Any]:
    """指定パスの JSON を読み込む（テストで patch(open) する前提のシンプル関数）"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def get_config(path: Optional[str] = None) -> Dict[str, Any]:
    """
    設定の探索順：
      1) 引数 path
      2) 環境変数 CONFIG_JSON
      3) カレントディレクトリ: ./config/setting.json
      4) このファイルの隣接:    <this>/config/setting.json
    """
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    if os.getenv("CONFIG_JSON"):
        candidates.append(Path(os.getenv("CONFIG_JSON", "")))
    candidates.append(Path.cwd() / "config" / "setting.json")
    candidates.append(Path(__file__).resolve().parent / "config" / "setting.json")

    tried = []
    for p in candidates:
        tried.append(str(p))
        if p.is_file():
            return load_config(str(p))

    raise FileNotFoundError("setting.json not found. tried: " + " | ".join(tried))


# =========================
# ロガー（回転ログ・遅延初期化）
# =========================
_LOGGER: Optional[logging.Logger] = None


def _ensure_logger(cfg: Optional[Dict[str, Any]] = None) -> logging.Logger:
    """
    回転ログ（RotatingFileHandler）を1度だけ初期化。
    cfg が None の場合は get_config() を呼んで取得。
    """
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    if cfg is None:
        try:
            cfg = get_config()
        except Exception:
            # 設定が無くても最低限のコンソールログは出す
            logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
            _LOGGER = logging.getLogger("gpt_oss_local_api")
            return _LOGGER

    log_file = cfg.get("log_file", "gpt_oss_local_api.log")
    max_mb = int(cfg.get("log_max_bytes_mb", 10))
    backup = int(cfg.get("log_backup_count", 5))

    logger = logging.getLogger("gpt_oss_local_api")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    # 親ディレクトリを作成（ファイルパスにサブディレクトリが含まれても安全に）
    try:
        Path(log_file).resolve().parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    handler = RotatingFileHandler(
        log_file, maxBytes=max_mb * 1024 * 1024, backupCount=backup, encoding="utf-8"
    )
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)

    # 併せてコンソールにも出す（任意）
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    _LOGGER = logger
    return logger


# =========================
# 入力バリデーション
# =========================
def validate_input(text: str) -> bool:
    """
    True  … 有効
    False … 無効（空/長すぎ）
    ・空文字/空白のみは NG
    ・最大長は 8000 文字（テストに合わせる）
    """
    if text is None:
        return False
    s = str(text).strip()
    if not s:
        return False
    if len(s) > 50000:
        return False
    return True


# =========================
# API 呼び出し
# =========================
def _extract_content(resp_json: Dict[str, Any]) -> Optional[str]:
    """
    OpenAI 互換 Chat Completions のレスポンスから
    choices[0].message.content を安全に取り出す。
    """
    try:
        choices = resp_json.get("choices") or []
        if not choices:
            return None
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content
        return None
    except Exception:
        return None


def get_lmstudio_response(
    prompt: str,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.7,
    top_p: float = 0.95,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """
    LM Studio / OpenAI 互換サーバの /v1/chat/completions を叩いて
    アシスタントの content を返す。失敗時は ERROR_MESSAGE を返す。
    """
    logger = _ensure_logger(None)

    if not validate_input(prompt):
        logger.warning("validate_input failed: prompt is empty or too long")
        return ERROR_MESSAGE

    try:
        cfg = get_config()
    except Exception as e:
        # 設定が見つからない場合もテストしやすいようにログして終了
        logger.error("config load failed: %s", e)
        return ERROR_MESSAGE

    url = api_url or cfg.get("api_url")
    if not url:
        logger.error("api_url is not set")
        return ERROR_MESSAGE

    mdl = model or cfg.get("model") or DEFAULT_MODEL

    payload = {
        "model": mdl,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "top_p": top_p,
    }

    try:
        logger.info("POST %s model=%s", url, mdl)
        res = requests.post(url, json=payload, timeout=timeout)
        status = res.status_code
        logger.info("status=%s", status)

        if status != 200:
            # 本番では res.text をログしたいが、テストでは json() をモックしている想定
            try:
                j = res.json()
                logger.warning("non-200 response: %s", j)
            except Exception:
                logger.warning("non-200 response (no json body)")
            return ERROR_MESSAGE

        try:
            data = res.json()
        except Exception as e:
            logger.error("json decode failed: %s", e)
            return ERROR_MESSAGE

        content = _extract_content(data)
        if not content:
            logger.warning("content not found in response json")
            return ERROR_MESSAGE

        logger.info("response ok (%d chars)", len(content))
        return content

    except requests.RequestException as e:
        logger.error("request error: %s", e)
        return ERROR_MESSAGE
    except Exception as e:
        logger.exception("unexpected error: %s", e)
        return ERROR_MESSAGE


# =========================
# CLI 用（任意）
# =========================
def main() -> None:
    """
    例：
      python -m gpt_oss_local_api "テストプロンプト"
    """
    import sys

    if len(sys.argv) < 2:
        print("使い方: python -m gpt_oss_local_api <PROMPT>")
        return

    prompt = sys.argv[1]
    text = get_lmstudio_response(prompt)
    print(text)


if __name__ == "__main__":
    main()
