from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.telegram.constants import CATEGORY_LABELS

JK_PAGE_SIZE = 6


def build_jk_keyboard(complexes: list[str], page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    total = len(complexes)
    total_pages = max((total - 1) // JK_PAGE_SIZE + 1, 1)
    current_page = max(0, min(page, total_pages - 1))

    start = current_page * JK_PAGE_SIZE
    end = start + JK_PAGE_SIZE
    for index, name in enumerate(complexes[start:end], start=start):
        builder.button(text=name, callback_data=f"jk_pick:{index}")
    builder.adjust(1)

    nav_row: list[tuple[str, str]] = []
    if current_page > 0:
        nav_row.append(("← Назад", f"jk_page:{current_page - 1}"))
    nav_row.append((f"{current_page + 1}/{total_pages}", "jk_page:stay"))
    if current_page < total_pages - 1:
        nav_row.append(("Вперед →", f"jk_page:{current_page + 1}"))

    for text, cb in nav_row:
        builder.button(text=text, callback_data=cb)
    builder.adjust(1, len(nav_row))
    builder.button(text="Другое / не знаю", callback_data="jk_unknown")
    builder.adjust(1, len(nav_row), 1)

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

