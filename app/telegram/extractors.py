from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.core.utils import normalize_phone, normalize_text

_RU_TO_LATIN = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


@dataclass(slots=True)
class ExtractedReportContext:
    jk: str | None = None
    house: str | None = None
    entrance: str | None = None
    apartment: str | None = None
    phone: str | None = None


def extract_report_context(text: str, housing_complexes: list[str]) -> ExtractedReportContext:
    source = text.strip()
    if not source:
        return ExtractedReportContext()

    return ExtractedReportContext(
        jk=_extract_jk(source, housing_complexes),
        house=_extract_token(
            source,
            (
                r"\bдом(?:\s+номер)?\s*№?\s*([0-9]+[0-9а-яa-z/-]*)",
                r"\bд\.\s*([0-9]+[0-9а-яa-z/-]*)",
            ),
        ),
        entrance=_extract_token(
            source,
            (
                r"\bпод(?:ъ|ь)?езд\s*№?\s*([0-9]+[0-9а-яa-z/-]*)",
                r"\bпод\.\s*([0-9]+[0-9а-яa-z/-]*)",
            ),
        ),
        apartment=_extract_token(
            source,
            (
                r"\bкв(?:артира)?\.?\s*№?\s*([0-9]+[0-9а-яa-z/-]*)",
                r"\bап(?:артамент)?\.?\s*([0-9]+[0-9а-яa-z/-]*)",
            ),
        ),
        phone=_extract_phone(source),
    )


def _extract_token(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_phone(text: str) -> str | None:
    for candidate in re.findall(r"(\+?\d[\d\-\(\)\s]{9,}\d)", text):
        phone = normalize_phone(candidate)
        if phone is not None:
            return phone
    return None


def _extract_jk(text: str, housing_complexes: list[str]) -> str | None:
    if not housing_complexes:
        return None

    normalized_text = _normalize_for_match(text)
    if not normalized_text:
        return None

    by_length = sorted(housing_complexes, key=len, reverse=True)
    for complex_name in by_length:
        if _normalize_for_match(complex_name) in normalized_text:
            return complex_name

    match = re.search(r"(?:жк|жил(?:ой|ого)?\s+комплекс)\s*[«\"']?([^,.;\n]{2,80})", text, flags=re.IGNORECASE)
    if not match:
        return None

    candidate = match.group(1).strip(" \"'«»")
    if not candidate:
        return None

    return _best_complex_match(candidate, housing_complexes)


def _best_complex_match(candidate: str, housing_complexes: list[str]) -> str | None:
    normalized_candidate = _normalize_for_match(candidate)
    normalized_candidate_lat = _to_latin(normalized_candidate)
    if not normalized_candidate:
        return None

    best_score = 0.0
    best_value: str | None = None
    for complex_name in housing_complexes:
        normalized_complex = _normalize_for_match(complex_name)
        normalized_complex_lat = _to_latin(normalized_complex)
        score_native = SequenceMatcher(a=normalized_candidate, b=normalized_complex).ratio()
        score_latin = SequenceMatcher(a=normalized_candidate_lat, b=normalized_complex_lat).ratio()
        score = max(score_native, score_latin)
        if (
            normalized_candidate in normalized_complex
            or normalized_complex in normalized_candidate
            or normalized_candidate_lat in normalized_complex_lat
            or normalized_complex_lat in normalized_candidate_lat
        ):
            score += 0.2
        if score > best_score:
            best_score = score
            best_value = complex_name

    if best_score < 0.66:
        return None
    return best_value


def _normalize_for_match(value: str) -> str:
    normalized = normalize_text(value).replace("ё", "е")
    normalized = re.sub(r"[«»\"'`]", " ", normalized)
    normalized = re.sub(r"[^a-zа-я0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _to_latin(value: str) -> str:
    out: list[str] = []
    for symbol in value:
        out.append(_RU_TO_LATIN.get(symbol, symbol))
    return "".join(out)
