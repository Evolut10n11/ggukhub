from __future__ import annotations

import pytest

from app.core.classifier import CategoryClassifier
from app.telegram.dialog.classification import DialogCategoryService


def _classifier() -> CategoryClassifier:
    return CategoryClassifier(
        {
            "elevator": {"label": "Elevator", "keywords": ["elevator", "lift"]},
            "other": {"label": "Other", "keywords": []},
        }
    )


@pytest.mark.asyncio
async def test_dialog_category_service_returns_rule_match() -> None:
    service = DialogCategoryService(_classifier())

    result = await service.classify("The elevator is broken")

    assert result.category == "elevator"
    assert result.source.value == "rules"


@pytest.mark.asyncio
async def test_dialog_category_service_returns_other_for_unknown() -> None:
    service = DialogCategoryService(_classifier())

    result = await service.classify("Something unclear happened")

    assert result.category == "other"
    assert result.source.value == "rules"
