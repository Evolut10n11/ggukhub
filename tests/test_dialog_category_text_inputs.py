from __future__ import annotations

from types import SimpleNamespace

from app.core.classifier import CategoryClassifier
from app.telegram.handlers.dialog import _category_from_text, _is_no_or_other_text, _is_yes_text


def _services_stub() -> SimpleNamespace:
    rules = {
        "water_off": {"label": "Нет воды", "keywords": ["нет воды"]},
        "elevator": {"label": "Лифт", "keywords": ["лифт"]},
        "other": {"label": "Другое", "keywords": []},
    }
    return SimpleNamespace(classifier=CategoryClassifier(rules))


def test_yes_no_text_helpers() -> None:
    assert _is_yes_text("да")
    assert _is_yes_text("подтверждаю")
    assert _is_no_or_other_text("другое")
    assert _is_no_or_other_text("нет")
    assert not _is_yes_text("позже")


def test_category_from_text_by_label_and_synonym() -> None:
    services = _services_stub()

    assert _category_from_text(services, "Лифт") == "elevator"
    assert _category_from_text(services, "нет воды") == "water_off"
    assert _category_from_text(services, "другое") == "other"

