from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class VectorDoc:
    source: str
    text: str
    metadata: Dict[str, Any]
