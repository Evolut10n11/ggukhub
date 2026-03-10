from __future__ import annotations

from types import SimpleNamespace

from app.core.classifier import CategoryClassifier
from app.telegram.dialog.state_machine import (
    is_report_status_request,
    is_saved_phone_accept_text,
    is_saved_phone_reject_text,
)
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


def test_phone_reuse_and_status_helpers() -> None:
    assert is_saved_phone_accept_text("использовать")
    assert is_saved_phone_accept_text("да")
    assert is_saved_phone_reject_text("другой")
    assert is_saved_phone_reject_text("нет")
    assert is_report_status_request("Что с моей заявкой?")
    assert not is_report_status_request("Лифт не работает")


def test_category_from_text_by_label_and_synonym() -> None:
    services = _services_stub()

    assert _category_from_text(services, "Лифт") == "elevator"
    assert _category_from_text(services, "нет воды") == "water_off"
    assert _category_from_text(services, "другое") == "other"
