from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from app.core.utils import normalize_text
from app.telegram.constants import CATEGORY_LABELS, UNKNOWN_JK_VALUE
from app.telegram.dialog.models import DialogSessionData, DialogStep
from app.telegram.extractors import ExtractedReportContext

_CATEGORY_TEXT_MAP: dict[str, set[str]] = {
    "suggestion": {"предложение", "предлагаю", "идея", "пожелание"},
    "accident": {"авария", "аварийная", "протечка", "затопление", "нет воды", "нет света", "лифт", "отопление", "канализация", "домофон"},
    "recalc": {"пересчет", "пересчёт", "квартплата", "перерасчет", "перерасчёт", "квитанция"},
    "complaint": {"жалоба", "жалуюсь", "грязно", "мусор", "не убирают", "воняет"},
    "other": {"другое", "другую", "иное"},
}

_SAVED_PHONE_ACCEPT_TEXTS = {"использовать", "используй", "use", "use phone"}
_SAVED_PHONE_REJECT_TEXTS = {"другой", "указать другой", "new phone", "change phone"}
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
    return normalize_text(str(value)) == normalize_text(UNKNOWN_JK_VALUE)


def merge_extracted_context(data: DialogSessionData, extracted: ExtractedReportContext) -> DialogSessionData:
    updated = data.model_copy(deep=True)

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
    value = normalize_text(text)
    return value in {"да", "верно", "подтверждаю", "ок", "окей", "yes"}


def is_no_or_other_text(text: str) -> bool:
    value = normalize_text(text)
    return value in {
        "нет",
        "неверно",
        "другое",
        "другую",
        "другой",
        "указать другой",
        "выбрать другую",
        "other",
        "no",
    }


def is_saved_phone_accept_text(text: str) -> bool:
    value = normalize_text(text)
    return is_yes_text(text) or value in _SAVED_PHONE_ACCEPT_TEXTS


def is_saved_phone_reject_text(text: str) -> bool:
    value = normalize_text(text)
    return is_no_or_other_text(text) or value in _SAVED_PHONE_REJECT_TEXTS


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

    labels = category_labels or CATEGORY_LABELS
    for code in available:
        if value == normalize_text(label_resolver(code)):
            return code
        if value == normalize_text(labels.get(code, "")):
            return code

    for code, variants in _CATEGORY_TEXT_MAP.items():
        if code not in available:
            continue
        if value in {normalize_text(token) for token in variants}:
            return code

    return None


def dialog_step(value: str) -> DialogStep:
    try:
        return DialogStep(value)
    except ValueError:
        return DialogStep.AWAITING_JK
