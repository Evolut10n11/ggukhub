from pathlib import Path

from app.core.classifier import CategoryClassifier


def _classifier() -> CategoryClassifier:
    root = Path(__file__).resolve().parents[1]
    return CategoryClassifier.from_file(root / "data" / "categories.json")


def test_classifies_water_off() -> None:
    classifier = _classifier()
    assert classifier.classify("Добрый вечер, у нас нет воды уже два часа") == "water_off"


def test_classifies_elevator() -> None:
    classifier = _classifier()
    assert classifier.classify("Лифт застрял на 8 этаже и не открывается") == "elevator"


def test_fallback_other() -> None:
    classifier = _classifier()
    assert classifier.classify("Хочу уточнить график работы офиса") == "other"


def test_classifies_protekaet_as_water_leak() -> None:
    classifier = _classifier()
    assert classifier.classify("Протекает вода в подъезде") == "water_leak"


def test_classifies_kholodno_as_heating() -> None:
    classifier = _classifier()
    assert classifier.classify("Холодно!") == "heating"


def test_classifies_smell_in_entrance_as_cleaning() -> None:
    classifier = _classifier()
    assert classifier.classify("В подъезде пахнет ужасно") == "cleaning"
