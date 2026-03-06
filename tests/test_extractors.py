from __future__ import annotations

from app.telegram.extractors import extract_report_context


def test_extract_report_context_full_voice_phrase() -> None:
    complexes = ["Pride Park", "Еврокласс", "Skyline-2"]
    text = "Лифт не работает. ЖК Pride Park, дом 5, подъезд 3, квартира 78, телефон +7 (900) 111-22-33."

    parsed = extract_report_context(text, complexes)

    assert parsed.jk == "Pride Park"
    assert parsed.house == "5"
    assert parsed.entrance == "3"
    assert parsed.apartment == "78"
    assert parsed.phone == "+79001112233"


def test_extract_report_context_detects_complex_by_substring() -> None:
    complexes = ["Green Park Солотча", "Окская стрелка"]
    text = "В Green Park Солотча не работает домофон, дом 12 к2, кв 44."

    parsed = extract_report_context(text, complexes)

    assert parsed.jk == "Green Park Солотча"
    assert parsed.house == "12"
    assert parsed.apartment == "44"


def test_extract_report_context_matches_cyrillic_to_latin_complex_name() -> None:
    complexes = ["Pride Park", "Skyline-2"]
    text = "ЖК Прайд Парк, лифт не работает, дом 5, подъезд 3, квартира 78"

    parsed = extract_report_context(text, complexes)

    assert parsed.jk == "Pride Park"
    assert parsed.house == "5"
    assert parsed.entrance == "3"
    assert parsed.apartment == "78"


def test_extract_report_context_returns_empty_when_not_found() -> None:
    parsed = extract_report_context("Просто холодно в квартире", ["Pride Park"])

    assert parsed.jk is None
    assert parsed.house is None
    assert parsed.entrance is None
    assert parsed.apartment is None
    assert parsed.phone is None
