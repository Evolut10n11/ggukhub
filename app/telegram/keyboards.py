from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.buildings import HouseInfo
from app.telegram.constants import CATEGORY_LABELS

JK_PAGE_SIZE = 8
JK_BUTTON_COLUMNS = 2
JK_BUTTON_MAX_LEN = 24
HOUSE_PAGE_SIZE = 8
MAIN_MENU_NEW_REQUEST = "Новая заявка"
MAIN_MENU_STATUS = "Статус заявки"

STANDALONE_JK_LABEL = "📍 Другой дом"


def _display_housing_complex_name(name: str) -> str:
    value = " ".join(str(name).split()).strip()
    if value.lower().startswith("жк "):
        value = value[3:].strip()
    if len(value) > JK_BUTTON_MAX_LEN:
        value = value[: JK_BUTTON_MAX_LEN - 1].rstrip() + "…"
    return value


def build_jk_keyboard(complex_names: list[str], page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    total = len(complex_names)
    total_pages = max((total - 1) // JK_PAGE_SIZE + 1, 1)
    current_page = max(0, min(page, total_pages - 1))

    start = current_page * JK_PAGE_SIZE
    end = start + JK_PAGE_SIZE
    visible = complex_names[start:end]

    for row_start in range(0, len(visible), JK_BUTTON_COLUMNS):
        row_buttons = [
            InlineKeyboardButton(
                text=_display_housing_complex_name(name),
                callback_data=f"jk_pick:{index}",
            )
            for index, name in enumerate(
                visible[row_start : row_start + JK_BUTTON_COLUMNS],
                start=start + row_start,
            )
        ]
        builder.row(*row_buttons)

    if total_pages > 1:
        nav_buttons: list[InlineKeyboardButton] = []
        if current_page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"jk_page:{current_page - 1}"))
        nav_buttons.append(
            InlineKeyboardButton(text=f"Стр. {current_page + 1}/{total_pages}", callback_data="jk_page:stay")
        )
        if current_page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="Вперед ▶", callback_data=f"jk_page:{current_page + 1}"))
        builder.row(*nav_buttons)

    builder.row(InlineKeyboardButton(text=STANDALONE_JK_LABEL, callback_data="jk_standalone"))
    builder.row(InlineKeyboardButton(text="📋 Статус заявки", callback_data="back_to_menu_status"))

    return builder.as_markup()


def build_house_keyboard(houses: list[HouseInfo], page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    total = len(houses)
    total_pages = max((total - 1) // HOUSE_PAGE_SIZE + 1, 1)
    current_page = max(0, min(page, total_pages - 1))

    start = current_page * HOUSE_PAGE_SIZE
    end = start + HOUSE_PAGE_SIZE
    visible = houses[start:end]

    for i, house in enumerate(visible):
        label = house.address
        if len(label) > 30:
            label = label[:29].rstrip() + "…"
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=f"house:{start + i}",
            )
        )

    if total_pages > 1:
        nav_buttons: list[InlineKeyboardButton] = []
        if current_page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"house_p:{current_page - 1}"))
        nav_buttons.append(
            InlineKeyboardButton(text=f"Стр. {current_page + 1}/{total_pages}", callback_data="house_p:stay")
        )
        if current_page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="Вперед ▶", callback_data=f"house_p:{current_page + 1}"))
        builder.row(*nav_buttons)

    return builder.as_markup()


def build_entrance_keyboard(entrances: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    buttons = [
        InlineKeyboardButton(text=str(n), callback_data=f"ent:{n}")
        for n in range(1, entrances + 1)
    ]
    cols = min(4, entrances)
    for row_start in range(0, len(buttons), cols):
        builder.row(*buttons[row_start : row_start + cols])
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


class TelegramKeyboardFactory:
    def jk_keyboard(self, complex_names: list[str], page: int) -> InlineKeyboardMarkup:
        return build_jk_keyboard(complex_names, page)

    def house_keyboard(self, houses: list[HouseInfo], page: int) -> InlineKeyboardMarkup:
        return build_house_keyboard(houses, page)

    def entrance_keyboard(self, entrances: int) -> InlineKeyboardMarkup:
        return build_entrance_keyboard(entrances)

    def category_confirm_keyboard(self) -> InlineKeyboardMarkup:
        return build_category_confirm_keyboard()

    def category_select_keyboard(self) -> InlineKeyboardMarkup:
        return build_category_select_keyboard()

    def report_confirm_keyboard(self) -> InlineKeyboardMarkup:
        return build_report_confirm_keyboard()

    def phone_reuse_keyboard(self, phone: str) -> InlineKeyboardMarkup:
        return build_phone_reuse_keyboard(phone)

    def address_reuse_keyboard(self) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="Да, адрес тот же", callback_data="address_reuse_yes")
        builder.button(text="Нет, другой адрес", callback_data="address_reuse_no")
        builder.adjust(1)
        return builder.as_markup()

    def new_report_keyboard(self) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="📝 Создать ещё заявку", callback_data="new_report")
        builder.adjust(1)
        return builder.as_markup()

    def back_to_menu_keyboard(self) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="🏠 Вернуться в меню", callback_data="back_to_menu")
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
