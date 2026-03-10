from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.core.utils import normalize_text

_WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+")
_LETTER_RE = re.compile(r"[A-Za-zА-Яа-яЁё]")
_PROFANITY_RE = re.compile(
    r"(?iu)\b(?:"
    r"бля(?:д(?:ь)?|т(?:ь)?|ха)?|"
    r"сук(?:а|и|ой|у|е)?|"
    r"еб(?:ан|ать|ёт|ет|ал|уч|ну|ись)?\w*|"
    r"пизд\w*|"
    r"ху(?:й|я|е|и|л)\w*|"
    r"мудак\w*|"
    r"дебил\w*|"
    r"идиот\w*|"
    r"нах(?:уй|ер)?"
    r")\b"
)
_LOW_SIGNAL_TOKENS = frozenset(
    {
        "1",
        "2",
        "3",
        "4",
        "5",
        "да",
        "нет",
        "ок",
        "ok",
        "ага",
        "алло",
        "эй",
        "привет",
        "заявка",
        "проблема",
        "срочно",
        "помогите",
    }
)


class ProblemTextIssue(str, Enum):
    EMPTY = "empty"
    TOO_SHORT = "too_short"
    LOW_SIGNAL = "low_signal"
    ABUSIVE = "abusive"


@dataclass(slots=True)
class ProblemTextValidationResult:
    is_valid: bool
    issue: ProblemTextIssue | None = None
    normalized_text: str = ""


def validate_problem_text(text: str) -> ProblemTextValidationResult:
    normalized = normalize_text(text)
    if not normalized:
        return ProblemTextValidationResult(is_valid=False, issue=ProblemTextIssue.EMPTY, normalized_text=normalized)

    if _PROFANITY_RE.search(normalized):
        return ProblemTextValidationResult(is_valid=False, issue=ProblemTextIssue.ABUSIVE, normalized_text=normalized)

    tokens = _WORD_RE.findall(normalized)
    letter_count = sum(1 for symbol in normalized if _LETTER_RE.fullmatch(symbol))
    if not tokens or letter_count == 0:
        return ProblemTextValidationResult(is_valid=False, issue=ProblemTextIssue.LOW_SIGNAL, normalized_text=normalized)

    if normalized in _LOW_SIGNAL_TOKENS:
        return ProblemTextValidationResult(is_valid=False, issue=ProblemTextIssue.LOW_SIGNAL, normalized_text=normalized)

    if len(tokens) == 1:
        token = tokens[0]
        if token in _LOW_SIGNAL_TOKENS:
            return ProblemTextValidationResult(
                is_valid=False,
                issue=ProblemTextIssue.LOW_SIGNAL,
                normalized_text=normalized,
            )
        token_letters = sum(1 for symbol in token if _LETTER_RE.fullmatch(symbol))
        if token_letters < 3:
            return ProblemTextValidationResult(
                is_valid=False,
                issue=ProblemTextIssue.TOO_SHORT,
                normalized_text=normalized,
            )

    if letter_count < 3:
        return ProblemTextValidationResult(is_valid=False, issue=ProblemTextIssue.TOO_SHORT, normalized_text=normalized)

    return ProblemTextValidationResult(is_valid=True, normalized_text=normalized)


def problem_text_rejection_message(result: ProblemTextValidationResult) -> str:
    if result.issue == ProblemTextIssue.ABUSIVE:
        return (
            "Опишите, пожалуйста, проблему без оскорблений: что произошло и где это случилось. "
            "Например: «не работает лифт в подъезде 1»."
        )
    return (
        "Нужно коротко и по делу описать саму проблему: что случилось и где. "
        "Например: «не работает лифт», «нет воды в квартире», «протечка в подъезде»."
    )
