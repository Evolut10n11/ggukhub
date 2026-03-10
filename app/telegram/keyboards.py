from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.telegram.constants import CATEGORY_LABELS

JK_PAGE_SIZE = 8
JK_BUTTON_COLUMNS = 2
JK_BUTTON_MAX_LEN = 24
MAIN_MENU_NEW_REQUEST = "Новая заявка"
MAIN_MENU_STATUS = "Статус заявки"


def _display_housing_complex_name(name: str) -> str:
    value = " ".join(str(name).split()).strip()
    if value.lower().startswith("жк "):
        value = value[3:].strip()
    if len(value) > JK_BUTTON_MAX_LEN:
        value = value[: JK_BUTTON_MAX_LEN - 1].rstrip() + "…"
    return value


def build_jk_keyboard(complexes: list[str], page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    total = len(complexes)
    total_pages = max((total - 1) // JK_PAGE_SIZE + 1, 1)
    current_page = max(0, min(page, total_pages - 1))

    start = current_page * JK_PAGE_SIZE
    end = start + JK_PAGE_SIZE
    visible_complexes = complexes[start:end]

    for row_start in range(0, len(visible_complexes), JK_BUTTON_COLUMNS):
        row_buttons = [
            InlineKeyboardButton(
                text=_display_housing_complex_name(name),
                callback_data=f"jk_pick:{index}",
            )
            for index, name in enumerate(
                visible_complexes[row_start : row_start + JK_BUTTON_COLUMNS],
                start=start + row_start,
            )
        ]
        builder.row(*row_buttons)

    nav_buttons: list[InlineKeyboardButton] = []
    if current_page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"jk_page:{current_page - 1}"))
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"Стр. {current_page + 1}/{total_pages}",
            callback_data="jk_page:stay",
        )
    )
    if current_page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ▶", callback_data=f"jk_page:{current_page + 1}"))
    builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(
            text="Не вижу / не знаю свой ЖК",
            callback_data="jk_unknown",
        )
    )

    return builder.as_markup()


def build_category_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да", callback_data="cat_yes")
    builder.button(text="Выбрать другую", callback_data="cat_other")
    builder.adjust(2)
    return builder.as_markup()


def build_category_select_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, label in CATEGORY_LABELS.items():
        builder.button(text=label, callback_data=f"cat_pick:{code}")
    builder.adjust(1)
    return builder.as_markup()


def build_report_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, все верно", callback_data="report_yes")
    builder.button(text="Нет, исправить", callback_data="report_edit")
    builder.adjust(1)
    return builder.as_markup()


def build_phone_reuse_keyboard(phone: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Использовать {phone}", callback_data="phone_reuse_yes")
    builder.button(text="Указать другой", callback_data="phone_reuse_other")
    builder.adjust(1)
    return builder.as_markup()


def build_main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=MAIN_MENU_NEW_REQUEST),
                KeyboardButton(text=MAIN_MENU_STATUS),
            ]
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Опишите проблему или выберите действие ниже",
    )
