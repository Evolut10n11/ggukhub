from __future__ import annotations

from app.core.category_resolution import CategoryResolutionResult, CategoryResolutionSource, CategoryResolver
from app.core.classifier import CategoryClassifier
from app.telegram.dialog.models import ClassificationResult, ClassificationSource


class DialogCategoryService:
    def __init__(self, classifier: CategoryClassifier, llm_resolver: CategoryResolver):
        self._classifier = classifier
        self._llm_resolver = llm_resolver

    async def classify(self, problem_text: str) -> ClassificationResult:
        rule_category = self._classifier.classify(problem_text)
        if rule_category != "other":
            return ClassificationResult(
                category=rule_category,
                source=ClassificationSource.RULES,
                fallback_used=False,
                metadata={"rule_category": rule_category},
            )

        llm_result = await self._llm_resolver.resolve(problem_text)
        if llm_result is None:
            llm_result = CategoryResolutionResult(
                category=None,
                source=CategoryResolutionSource.LLM,
                fallback_used=True,
                metadata={"reason": "resolver_returned_none"},
            )
        if llm_result.category is not None:
            return ClassificationResult(
                category=llm_result.category,
                source=ClassificationSource.LLM,
                raw_output=llm_result.raw_output,
                timed_out=llm_result.timed_out,
                fallback_used=llm_result.fallback_used,
                metadata=dict(llm_result.metadata),
            )

        metadata = dict(llm_result.metadata)
        metadata["rule_category"] = rule_category
        return ClassificationResult(
            category=rule_category,
            source=ClassificationSource.RULES,
            raw_output=llm_result.raw_output,
            timed_out=llm_result.timed_out,
            fallback_used=True,
            metadata=metadata,
        )
