from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from app.core.utils import normalize_text
from app.telegram.constants import CATEGORY_LABELS, UNKNOWN_JK_VALUE
from app.telegram.dialog.models import DialogSessionData, DialogStep
from app.telegram.extractors import ExtractedReportContext

_NORMALIZED_UNKNOWN_JK = normalize_text(UNKNOWN_JK_VALUE)

_CATEGORY_TEXT_MAP: dict[str, frozenset[str]] = {
    code: frozenset(normalize_text(t) for t in variants)
    for code, variants in {
        "suggestion": {"предложение", "предлагаю", "идея", "пожелание"},
        "accident": {"авария", "аварийная", "протечка", "затопление", "нет воды", "нет света", "лифт", "отопление", "канализация", "домофон"},
        "recalc": {"пересчет", "пересчёт", "квартплата", "перерасчет", "перерасчёт", "квитанция"},
        "complaint": {"жалоба", "жалуюсь", "грязно", "мусор", "не убирают", "воняет"},
        "other": {"другое", "другую", "иное"},
    }.items()
}

_YES_TEXTS = frozenset({"да", "верно", "подтверждаю", "ок", "окей", "yes"})
_NO_TEXTS = frozenset({"нет", "неверно", "другое", "другую", "другой", "указать другой", "выбрать другую", "other", "no"})
_SAVED_PHONE_ACCEPT_TEXTS = _YES_TEXTS | frozenset({"использовать", "используй", "use", "use phone"})
_SAVED_PHONE_REJECT_TEXTS = _NO_TEXTS | frozenset({"другой", "указать другой", "new phone", "change phone"})
_REPORT_STATUS_PATTERNS = (
    "что с моей заявкой",
    "что по моей заявке",
    "какой статус у моей заявки",
    "статус моей заявки",
    "у вас осталась моя заявка",
    "моя прошлая заявка",
    "моя предыдущая заявка",
    "что с прошлой заявкой",
    "статус заявки",
)

# Pre-normalize category labels for fast lookup
_NORMALIZED_CATEGORY_LABELS: dict[str, str] = {
    code: normalize_text(label) for code, label in CATEGORY_LABELS.items()
}


def cleanup_optional_field(raw: str) -> str | None:
    value = raw.strip().lower()
    if value in {"", "-", "нет", "не знаю", "n/a"}:
        return None
    return raw.strip()


def is_blank(value: str | None) -> bool:
    return value is None or not str(value).strip()


def is_unknown_jk(value: str | None) -> bool:
    if is_blank(value):
        return True
    return normalize_text(str(value)) == _NORMALIZED_UNKNOWN_JK


def merge_extracted_context(data: DialogSessionData, extracted: ExtractedReportContext) -> DialogSessionData:
    updated = data.model_copy()

    if extracted.jk and is_unknown_jk(updated.jk):
        updated.jk = extracted.jk
    if extracted.house and is_blank(updated.house):
        updated.house = extracted.house
    if extracted.entrance and is_blank(updated.entrance):
        updated.entrance = extracted.entrance
    if extracted.apartment and is_blank(updated.apartment):
        updated.apartment = extracted.apartment
    if extracted.phone:
        updated.phone = extracted.phone

    return updated


def collected_fields_text(data: DialogSessionData, user_phone: str | None = None) -> str:
    jk = str(data.jk or "").strip()
    house = str(data.house or "").strip()
    entrance = str(data.entrance or "").strip()
    apartment = str(data.apartment or "").strip()
    phone = str(data.phone or user_phone or "").strip()

    return (
        "По голосовому зафиксировала данные:\n"
        f"ЖК: {jk or 'не указан'}\n"
        f"Дом: {house or 'не указан'}\n"
        f"Подъезд: {entrance or 'не указан'}\n"
        f"Квартира: {apartment or 'не указана'}\n"
        f"Телефон: {phone or 'не указан'}"
    )


def next_missing_step(data: DialogSessionData, user_phone: str | None) -> DialogStep:
    jk = str(data.jk or "").strip()
    house = str(data.house or "").strip()
    apartment = str(data.apartment or "").strip()
    phone = str(data.phone or "").strip()
    saved_phone = str(user_phone or "").strip()
    problem_text = str(data.problem_text or "").strip()

    if is_unknown_jk(jk):
        return DialogStep.AWAITING_JK
    if not house:
        return DialogStep.AWAITING_HOUSE
    if _entrance_answer_pending(data):
        return DialogStep.AWAITING_ENTRANCE
    if not apartment:
        return DialogStep.AWAITING_APARTMENT
    if not phone and saved_phone:
        if not problem_text:
            return DialogStep.AWAITING_PROBLEM
        return DialogStep.AWAITING_PHONE_REUSE_CONFIRM
    if not phone:
        return DialogStep.AWAITING_PHONE
    if not problem_text:
        return DialogStep.AWAITING_PROBLEM
    return DialogStep.AWAITING_REPORT_CONFIRM


def _entrance_answer_pending(data: DialogSessionData) -> bool:
    if "entrance" not in data.model_fields_set:
        return True
    if data.entrance is None:
        return False
    return not str(data.entrance).strip()


def is_yes_text(text: str) -> bool:
    return normalize_text(text) in _YES_TEXTS


def is_no_or_other_text(text: str) -> bool:
    return normalize_text(text) in _NO_TEXTS


def is_saved_phone_accept_text(text: str) -> bool:
    return normalize_text(text) in _SAVED_PHONE_ACCEPT_TEXTS


def is_saved_phone_reject_text(text: str) -> bool:
    return normalize_text(text) in _SAVED_PHONE_REJECT_TEXTS


def is_report_status_request(text: str) -> bool:
    value = normalize_text(text)
    if not value:
        return False
    return any(pattern in value for pattern in _REPORT_STATUS_PATTERNS)


def category_from_text(
    text: str,
    *,
    categories: Iterable[str],
    label_resolver: Callable[[str], str],
    category_labels: Mapping[str, str] | None = None,
) -> str | None:
    value = normalize_text(text)
    if not value:
        return None

    available = list(categories)
    if value in available:
        return value

    # Check against pre-normalized labels first
    for code in available:
        if value == _NORMALIZED_CATEGORY_LABELS.get(code, ""):
            return code

    # Fallback to dynamic label resolver
    if category_labels:
        for code in available:
            if value == normalize_text(category_labels.get(code, "")):
                return code

    for code, variants in _CATEGORY_TEXT_MAP.items():
        if code in available and value in variants:
            return code

    return None


def dialog_step(value: str) -> DialogStep:
    try:
        return DialogStep(value)
    except ValueError:
        return DialogStep.AWAITING_JK
