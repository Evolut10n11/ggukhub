from __future__ import annotations

from typing import Any

from app.core.buildings import HouseInfo
from app.telegram.constants import CATEGORY_LABELS

JK_PAGE_SIZE = 8
JK_BUTTON_COLUMNS = 2
JK_BUTTON_MAX_LEN = 24
HOUSE_PAGE_SIZE = 8
STANDALONE_JK_LABEL = "📍 Другой дом"


def _inline_keyboard_attachment(buttons: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """Wrap button rows into MAX inline_keyboard attachment."""
    return {
        "type": "inline_keyboard",
        "payload": {"buttons": buttons},
    }


def _cb_button(text: str, payload: str) -> dict[str, Any]:
    return {"type": "callback", "text": text, "payload": payload}


def _display_name(name: str) -> str:
    value = " ".join(str(name).split()).strip()
    if value.lower().startswith("жк "):
        value = value[3:].strip()
    if len(value) > JK_BUTTON_MAX_LEN:
        value = value[: JK_BUTTON_MAX_LEN - 1].rstrip() + "…"
    return value


class MaxKeyboardFactory:
    """Builds MAX inline_keyboard attachments matching KeyboardFactory protocol."""

    def jk_keyboard(self, complex_names: list[str], page: int) -> list[dict[str, Any]]:
        total = len(complex_names)
        total_pages = max((total - 1) // JK_PAGE_SIZE + 1, 1)
        current_page = max(0, min(page, total_pages - 1))

        start = current_page * JK_PAGE_SIZE
        end = start + JK_PAGE_SIZE
        visible = complex_names[start:end]

        rows: list[list[dict[str, Any]]] = []
        for row_start in range(0, len(visible), JK_BUTTON_COLUMNS):
            row = [
                _cb_button(_display_name(name), f"jk_pick:{idx}")
                for idx, name in enumerate(
                    visible[row_start : row_start + JK_BUTTON_COLUMNS],
                    start=start + row_start,
                )
            ]
            rows.append(row)

        if total_pages > 1:
            nav: list[dict[str, Any]] = []
            if current_page > 0:
                nav.append(_cb_button("◀ Назад", f"jk_page:{current_page - 1}"))
            nav.append(_cb_button(f"Стр. {current_page + 1}/{total_pages}", "jk_page:stay"))
            if current_page < total_pages - 1:
                nav.append(_cb_button("Вперед ▶", f"jk_page:{current_page + 1}"))
            rows.append(nav)

        rows.append([_cb_button(STANDALONE_JK_LABEL, "jk_standalone")])
        rows.append([_cb_button("📋 Статус заявки", "back_to_menu_status")])
        rows.append([_cb_button("📞 Обращение в УК", "contact_operator")])
        return [_inline_keyboard_attachment(rows)]

    def house_keyboard(self, houses: list[HouseInfo], page: int) -> list[dict[str, Any]]:
        total = len(houses)
        total_pages = max((total - 1) // HOUSE_PAGE_SIZE + 1, 1)
        current_page = max(0, min(page, total_pages - 1))

        start = current_page * HOUSE_PAGE_SIZE
        end = start + HOUSE_PAGE_SIZE
        visible = houses[start:end]

        rows: list[list[dict[str, Any]]] = []
        for i, house in enumerate(visible):
            label = house.address
            if len(label) > 30:
                label = label[:29].rstrip() + "…"
            rows.append([_cb_button(label, f"house:{start + i}")])

        if total_pages > 1:
            nav: list[dict[str, Any]] = []
            if current_page > 0:
                nav.append(_cb_button("◀ Назад", f"house_p:{current_page - 1}"))
            nav.append(_cb_button(f"Стр. {current_page + 1}/{total_pages}", "house_p:stay"))
            if current_page < total_pages - 1:
                nav.append(_cb_button("Вперед ▶", f"house_p:{current_page + 1}"))
            rows.append(nav)

        return [_inline_keyboard_attachment(rows)]

    def entrance_keyboard(self, entrances: int) -> list[dict[str, Any]]:
        rows: list[list[dict[str, Any]]] = []
        cols = min(4, entrances)
        buttons = [_cb_button(str(n), f"ent:{n}") for n in range(1, entrances + 1)]
        for row_start in range(0, len(buttons), cols):
            rows.append(buttons[row_start : row_start + cols])
        return [_inline_keyboard_attachment(rows)]

    def category_confirm_keyboard(self) -> list[dict[str, Any]]:
        return [_inline_keyboard_attachment([
            [_cb_button("Да", "cat_yes"), _cb_button("Выбрать другую", "cat_other")]
        ])]

    def category_select_keyboard(self) -> list[dict[str, Any]]:
        rows = [[_cb_button(label, f"cat_pick:{code}")] for code, label in CATEGORY_LABELS.items()]
        return [_inline_keyboard_attachment(rows)]

    def report_confirm_keyboard(self) -> list[dict[str, Any]]:
        return [_inline_keyboard_attachment([
            [_cb_button("Да, все верно", "report_yes")],
            [_cb_button("Нет, исправить", "report_edit")],
        ])]

    def phone_reuse_keyboard(self, phone: str) -> list[dict[str, Any]]:
        return [_inline_keyboard_attachment([
            [_cb_button(f"Использовать {phone}", "phone_reuse_yes")],
            [_cb_button("Указать другой", "phone_reuse_other")],
        ])]

    def address_reuse_keyboard(self) -> list[dict[str, Any]]:
        return [_inline_keyboard_attachment([
            [_cb_button("Да, адрес тот же", "address_reuse_yes")],
            [_cb_button("Нет, другой адрес", "address_reuse_no")],
        ])]

    def new_report_keyboard(self) -> list[dict[str, Any]]:
        return [_inline_keyboard_attachment([
            [_cb_button("📝 Создать ещё заявку", "new_report")],
            [_cb_button("📞 Обращение в УК", "contact_operator")],
        ])]

    def back_to_menu_keyboard(self) -> list[dict[str, Any]]:
        return [_inline_keyboard_attachment([
            [_cb_button("🏠 Вернуться в меню", "back_to_menu")],
            [_cb_button("📞 Обращение в УК", "contact_operator")],
        ])]

    def close_operator_chat_keyboard(self) -> list[dict[str, Any]]:
        return [_inline_keyboard_attachment([
            [_cb_button("❌ Завершить чат с оператором", "close_operator_chat")],
        ])]

    def operator_report_keyboard(self, report_id: int) -> list[dict[str, Any]]:
        return [_inline_keyboard_attachment([
            [_cb_button("👀 Взять в работу", f"op_take:{report_id}")],
            [_cb_button("💬 Ответить", f"op_reply:{report_id}")],
            [_cb_button("✅ Закрыть", f"op_close:{report_id}")],
        ])]
