from __future__ import annotations

from app.core.category_resolution import CategoryResolutionResult, CategoryResolutionSource, CategoryResolver
from app.core.classifier import CategoryClassifier
from app.core.telemetry import start_flow_telemetry
from app.telegram.dialog.models import ClassificationResult, ClassificationSource


class DialogCategoryService:
    def __init__(self, classifier: CategoryClassifier, llm_resolver: CategoryResolver):
        self._classifier = classifier
        self._llm_resolver = llm_resolver

    async def classify(self, problem_text: str) -> ClassificationResult:
        llm_enabled = bool(getattr(self._llm_resolver, "enabled", False))
        budget_ms = None
        llm_settings = getattr(self._llm_resolver, "_settings", None)
        if llm_settings is not None:
            hard_timeout = float(getattr(llm_settings, "llm_category_timeout_seconds", 0) or 0)
            soft_timeout = float(getattr(llm_settings, "llm_category_soft_timeout_seconds", 0) or 0)
            effective_timeout = min(value for value in (hard_timeout, soft_timeout) if value > 0) if (hard_timeout > 0 or soft_timeout > 0) else 0
            budget_ms = int(effective_timeout * 1000) or None
        telemetry = start_flow_telemetry(
            "category_resolution",
            "resolve_category",
            budget_ms=budget_ms,
            llm_enabled=llm_enabled,
        )
        rule_category = self._classifier.classify(problem_text)
        if rule_category != "other":
            metadata = {"rule_category": rule_category}
            metadata["telemetry"] = telemetry.finish(
                rule_category=rule_category,
                rule_vs_llm_path="rules",
                fallback_used=False,
                timeout_occurred=False,
            )
            return ClassificationResult(
                category=rule_category,
                source=ClassificationSource.RULES,
                fallback_used=False,
                metadata=metadata,
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
            metadata = dict(llm_result.metadata)
            metadata["telemetry"] = telemetry.finish(
                raw_output=llm_result.raw_output,
                fallback_used=llm_result.fallback_used,
                timeout_occurred=llm_result.timed_out,
                rule_vs_llm_path="llm",
            )
            return ClassificationResult(
                category=llm_result.category,
                source=ClassificationSource.LLM,
                raw_output=llm_result.raw_output,
                timed_out=llm_result.timed_out,
                fallback_used=llm_result.fallback_used,
                metadata=metadata,
            )

        metadata = dict(llm_result.metadata)
        metadata["rule_category"] = rule_category
        metadata["telemetry"] = telemetry.finish(
            raw_output=llm_result.raw_output,
            fallback_used=True,
            timeout_occurred=llm_result.timed_out,
            rule_vs_llm_path="rules_with_llm_fallback",
        )
        return ClassificationResult(
            category=rule_category,
            source=ClassificationSource.RULES,
            raw_output=llm_result.raw_output,
            timed_out=llm_result.timed_out,
            fallback_used=True,
            metadata=metadata,
        )
