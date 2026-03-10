from __future__ import annotations

import pytest

from app.core.category_resolution import CategoryResolutionResult, CategoryResolutionSource
from app.core.classifier import CategoryClassifier
from app.telegram.dialog.classification import DialogCategoryService


class _LLMResolverStub:
    def __init__(self, result: CategoryResolutionResult) -> None:
        self._result = result
        self.calls: list[str] = []

    async def resolve(self, text: str) -> CategoryResolutionResult:
        self.calls.append(text)
        return self._result


def _classifier() -> CategoryClassifier:
    return CategoryClassifier(
        {
            "elevator": {"label": "Elevator", "keywords": ["elevator", "lift"]},
            "other": {"label": "Other", "keywords": []},
        }
    )


@pytest.mark.asyncio
async def test_dialog_category_service_prefers_rule_match_without_llm_call() -> None:
    llm_stub = _LLMResolverStub(
        CategoryResolutionResult(
            category="other",
            source=CategoryResolutionSource.LLM,
        )
    )
    service = DialogCategoryService(_classifier(), llm_stub)

    result = await service.classify("The elevator is broken")

    assert result.category == "elevator"
    assert result.source.value == "rules"
    assert not llm_stub.calls


@pytest.mark.asyncio
async def test_dialog_category_service_uses_llm_result_when_rules_return_other() -> None:
    llm_stub = _LLMResolverStub(
        CategoryResolutionResult(
            category="elevator",
            source=CategoryResolutionSource.LLM,
            raw_output="elevator",
        )
    )
    service = DialogCategoryService(_classifier(), llm_stub)

    result = await service.classify("The cabin stopped between floors")

    assert result.category == "elevator"
    assert result.source.value == "llm"
    assert result.raw_output == "elevator"
    assert llm_stub.calls == ["The cabin stopped between floors"]


@pytest.mark.asyncio
async def test_dialog_category_service_preserves_llm_fallback_metadata() -> None:
    llm_stub = _LLMResolverStub(
        CategoryResolutionResult(
            category=None,
            source=CategoryResolutionSource.LLM,
            raw_output="???",
            timed_out=True,
            fallback_used=True,
            metadata={"reason": "timeout"},
        )
    )
    service = DialogCategoryService(_classifier(), llm_stub)

    result = await service.classify("Something unclear happened")

    assert result.category == "other"
    assert result.source.value == "rules"
    assert result.timed_out is True
    assert result.fallback_used is True
    assert result.raw_output == "???"
    assert result.metadata == {"reason": "timeout", "rule_category": "other"}
