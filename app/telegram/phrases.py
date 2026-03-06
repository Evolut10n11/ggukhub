from __future__ import annotations

import re

GREETING_PHRASES = (
    "привет",
    "здравствуй",
    "здравствуйте",
    "добрый день",
    "добрый вечер",
    "доброе утро",
)

FAREWELL_PHRASES = (
    "спасибо",
    "благодарю",
    "пока",
    "до свидания",
    "всего доброго",
    "хорошего дня",
    "до встречи",
)


def normalize_user_text(text: str) -> str:
    value = text.strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


def is_greeting(text: str) -> bool:
    normalized = normalize_user_text(text)
    return any(phrase in normalized for phrase in GREETING_PHRASES)


def is_farewell_or_thanks(text: str) -> bool:
    normalized = normalize_user_text(text)
    return any(phrase in normalized for phrase in FAREWELL_PHRASES)

