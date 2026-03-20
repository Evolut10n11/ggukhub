from __future__ import annotations

from app.core.classifier import CategoryClassifier
from app.telegram.dialog.models import ClassificationResult, ClassificationSource


class DialogCategoryService:
    def __init__(self, classifier: CategoryClassifier):
        self._classifier = classifier

    async def classify(self, problem_text: str) -> ClassificationResult:
        category = self._classifier.classify(problem_text)
        return ClassificationResult(
            category=category,
            source=ClassificationSource.RULES,
        )
