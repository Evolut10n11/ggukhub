from __future__ import annotations

from app.telegram.extractors import (
    extract_apartment,
    extract_entrance,
    extract_house,
    extract_housing_complex,
    extract_phone,
    extract_report_context,
)


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


def test_extract_phone_helper_normalizes_number() -> None:
    assert extract_phone("Мой телефон 8 (900) 111-22-33") == "+79001112233"


def test_extract_address_helpers_parse_tokens_independently() -> None:
    assert extract_house("дом 15") == "15"
    assert extract_entrance("подъезд 4") == "4"
    assert extract_apartment("квартира 99") == "99"


def test_extract_housing_complex_helper_handles_partial_name() -> None:
    complexes = ["Pride Park", "Green Park Солотча"]
    assert extract_housing_complex("ЖК Прайд Парк, нет воды", complexes) == "Pride Park"


def test_extract_housing_complex_does_not_match_generic_park_noise() -> None:
    complexes = ["Pride Park", "Green Park Солотча"]
    assert extract_housing_complex("Рядом с парком грязно и скользко", complexes) is None


def test_extract_phone_ignores_short_or_invalid_numbers() -> None:
    assert extract_phone("Наберите мне на 12345") is None
    assert extract_phone("Телефон: 8-900") is None


def test_extract_address_helpers_do_not_confuse_house_and_apartment() -> None:
    text = "подъезд 4, квартира 99"
    assert extract_house(text) is None
    assert extract_entrance(text) == "4"
    assert extract_apartment(text) == "99"


def test_extract_housing_complex_prefers_transliterated_match_over_partial_noise() -> None:
    complexes = ["Pride Park", "Grand Comfort-3"]
    assert extract_housing_complex("ЖК Гранд Комфорт 3, пахнет в коридоре", complexes) == "Grand Comfort-3"
