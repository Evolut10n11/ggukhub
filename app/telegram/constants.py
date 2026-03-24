from __future__ import annotations

from app.telegram.dialog.models import DialogStep

STEP_IDLE = DialogStep.IDLE.value
STEP_AWAITING_JK = DialogStep.AWAITING_JK.value
STEP_AWAITING_HOUSE = DialogStep.AWAITING_HOUSE.value
STEP_AWAITING_ENTRANCE = DialogStep.AWAITING_ENTRANCE.value
STEP_AWAITING_APT = DialogStep.AWAITING_APARTMENT.value
STEP_AWAITING_PHONE = DialogStep.AWAITING_PHONE.value
STEP_AWAITING_PROBLEM = DialogStep.AWAITING_PROBLEM.value
STEP_AWAITING_PHONE_REUSE_CONFIRM = DialogStep.AWAITING_PHONE_REUSE_CONFIRM.value
STEP_AWAITING_CATEGORY_CONFIRM = DialogStep.AWAITING_CATEGORY_CONFIRM.value
STEP_AWAITING_CATEGORY_SELECT = DialogStep.AWAITING_CATEGORY_SELECT.value
STEP_AWAITING_REPORT_CONFIRM = DialogStep.AWAITING_REPORT_CONFIRM.value
STEP_AWAITING_REPORT_CORRECTION = DialogStep.AWAITING_REPORT_CORRECTION.value

UNKNOWN_JK_VALUE = "не знаю"

CATEGORY_LABELS = {
    "suggestion": "Предложение",
    "accident": "Сообщение об аварии",
    "recalc": "Пересчёт квартплаты",
    "complaint": "Жалоба",
    "other": "Иное",
}

WELCOME_TEXT = (
    "Здравствуйте!\n"
    "Я бот управляющей компании «Зелёный сад».\n\n"
    "Через меня можно быстро отправить заявку в диспетчерскую — текстом или голосом.\n\n"
    "Сначала выберите ваш жилой комплекс:"
)
