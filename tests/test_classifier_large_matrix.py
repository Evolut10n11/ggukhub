from __future__ import annotations

from collections import Counter
from pathlib import Path

from app.core.classifier import CategoryClassifier
from app.core.utils import load_json


def _classifier() -> CategoryClassifier:
    root = Path(__file__).resolve().parents[1]
    return CategoryClassifier.from_file(root / "data" / "categories.json")


def _rules() -> dict[str, dict[str, object]]:
    root = Path(__file__).resolve().parents[1]
    return load_json(root / "data" / "categories.json")


def _generated_keyword_cases() -> list[tuple[str, str]]:
    templates = [
        "{keyword}",
        "Проблема: {keyword}.",
        "У нас {keyword} в доме.",
        "{keyword}, помогите пожалуйста.",
    ]
    cases: list[tuple[str, str]] = []

    for category, payload in _rules().items():
        if category == "other":
            continue
        keywords = payload.get("keywords", [])
        if not isinstance(keywords, list):
            continue

        for keyword in keywords:
            for template in templates:
                cases.append((template.format(keyword=str(keyword)), category))

    return cases


def _manual_real_world_cases() -> list[tuple[str, str]]:
    return [
        ("Холодно дома, батареи почти ледяные", "heating"),
        ("Нас заливает с потолка в ванной", "water_leak"),
        ("Во всем подъезде пропал свет", "electricity_off"),
        ("Лифт застрял между этажами", "elevator"),
        ("Воняет канализацией в санузле", "sewage"),
        ("Домофон не открывает дверь по коду", "intercom"),
        ("В подъезде мусор и очень грязно", "cleaning"),
        ("Воды нет уже два часа", "water_off"),
        ("Нужна консультация по договору", "other"),
        ("Подскажите, как передать показания", "other"),
    ]


def _cases() -> list[tuple[str, str]]:
    return [*_generated_keyword_cases(), *_manual_real_world_cases()]


def test_classifier_large_matrix() -> None:
    classifier = _classifier()
    cases = _cases()
    mismatches: list[str] = []

    for idx, (text, expected) in enumerate(cases, start=1):
        predicted = classifier.classify(text)
        if predicted != expected:
            mismatches.append(f"{idx}. expected={expected}, predicted={predicted}, text={text!r}")

    assert not mismatches, "Large matrix mismatches:\n" + "\n".join(mismatches[:30])


def test_classifier_large_matrix_distribution() -> None:
    cases = _cases()
    counts = Counter(expected for _, expected in cases)
    minimums = {
        "water_off": 20,
        "water_leak": 20,
        "electricity_off": 20,
        "elevator": 15,
        "heating": 20,
        "sewage": 15,
        "intercom": 15,
        "cleaning": 15,
        "other": 2,
    }

    for category, minimum in minimums.items():
        assert counts[category] >= minimum
