from __future__ import annotations

STEP_IDLE = "idle"
STEP_AWAITING_JK = "awaiting_jk"
STEP_AWAITING_HOUSE = "awaiting_house"
STEP_AWAITING_ENTRANCE = "awaiting_entrance"
STEP_AWAITING_APT = "awaiting_apartment"
STEP_AWAITING_PHONE = "awaiting_phone"
STEP_AWAITING_PROBLEM = "awaiting_problem"
STEP_AWAITING_CATEGORY_CONFIRM = "awaiting_category_confirm"
STEP_AWAITING_CATEGORY_SELECT = "awaiting_category_select"

UNKNOWN_JK_VALUE = "не знаю"

CATEGORY_LABELS = {
    "water_off": "Нет воды",
    "water_leak": "Протечка / затопление",
    "electricity_off": "Нет электричества",
    "elevator": "Лифт",
    "heating": "Отопление",
    "sewage": "Канализация",
    "intercom": "Домофон",
    "cleaning": "Уборка",
    "other": "Другое",
}

WELCOME_TEXT = (
    "Здравствуйте!\n"
    "Я бот управляющей компании «Зелёный сад».\n\n"
    "Через меня можно быстро отправить заявку в диспетчерскую — текстом или голосом.\n\n"
    "Сначала выберите ваш жилой комплекс:"
)
