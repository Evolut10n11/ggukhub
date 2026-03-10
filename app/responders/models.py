from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ResponseGeneratorSource(str, Enum):
    RULES = "rules"
    LLM = "llm"


@dataclass(slots=True)
class GeneratedResponse:
    text: str
    source: ResponseGeneratorSource
    fallback_used: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
