from __future__ import annotations

from typing import Any, Dict, List

import requests


def embed_texts(cfg: Dict[str, Any], texts: List[str], timeout: int = 60) -> List[List[float]]:
    url = cfg.get("embeddings_url")
    model = cfg.get("embeddings_model")
    if not url or not model:
        raise RuntimeError("setting.json is missing embeddings_url or embeddings_model")

    payload = {"model": model, "input": texts}
    res = requests.post(url, json=payload, timeout=timeout)
    if res.status_code != 200:
        raise RuntimeError(f"Embeddings API returned {res.status_code}: {res.text[:500]}")

    data = res.json()
    items = data.get("data")
    if not isinstance(items, list):
        raise RuntimeError("Embeddings API response missing data[]")

    out: List[List[float]] = []
    for item in items:
        emb = item.get("embedding")
        if not isinstance(emb, list):
            raise RuntimeError("Embeddings API item missing embedding[]")
        out.append([float(v) for v in emb])
    return out
