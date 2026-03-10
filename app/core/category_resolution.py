from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class CategoryResolutionSource(str, Enum):
    RULES = "rules"
    LLM = "llm"
    MANUAL = "manual"


@dataclass(slots=True)
class CategoryResolutionResult:
    category: str | None
    source: CategoryResolutionSource
    raw_output: str | None = None
    timed_out: bool = False
    fallback_used: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class CategoryResolver(Protocol):
    async def resolve(self, text: str) -> CategoryResolutionResult:
        raise NotImplementedError
