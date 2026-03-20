from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class GeneratedResponse:
    text: str
    fallback_used: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
