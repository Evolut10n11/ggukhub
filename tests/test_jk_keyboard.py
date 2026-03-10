from __future__ import annotations

from app.telegram.keyboards import (
    JK_BUTTON_MAX_LEN,
    MAIN_MENU_NEW_REQUEST,
    MAIN_MENU_STATUS,
    build_jk_keyboard,
    build_main_menu_keyboard,
)


def test_jk_keyboard_uses_two_column_layout_and_unknown_action() -> None:
    complexes = [
        "Еврокласс",
        "Grand Comfort",
        "Grand Comfort-2",
        "Grand Comfort-3",
        "Pride Park",
        "Green Park Солотча-2",
        "Green Park Солотча",
        "ЖК «Евросити»",
        "Skyline",
    ]

    markup = build_jk_keyboard(complexes, page=0)
    rows = markup.inline_keyboard

    assert len(rows[0]) == 2
    assert len(rows[1]) == 2
    assert len(rows[2]) == 2
    assert len(rows[3]) == 2
    assert [button.text for button in rows[0]] == ["Еврокласс", "Grand Comfort"]
    assert rows[3][1].text == "«Евросити»"

    nav_row = rows[-2]
    assert [button.text for button in nav_row] == ["Стр. 1/2", "Вперед ▶"]
    assert [button.callback_data for button in nav_row] == ["jk_page:stay", "jk_page:1"]

    unknown_row = rows[-1]
    assert len(unknown_row) == 1
    assert unknown_row[0].text == "Не вижу / не знаю свой ЖК"
    assert unknown_row[0].callback_data == "jk_unknown"


def test_jk_keyboard_shows_back_and_forward_navigation_on_middle_pages() -> None:
    complexes = [f"Complex {index}" for index in range(18)]

    markup = build_jk_keyboard(complexes, page=1)
    nav_row = markup.inline_keyboard[-2]

    assert [button.text for button in nav_row] == ["◀ Назад", "Стр. 2/3", "Вперед ▶"]
    assert [button.callback_data for button in nav_row] == ["jk_page:0", "jk_page:stay", "jk_page:2"]


def test_jk_keyboard_shortens_long_names_for_button_labels() -> None:
    complexes = ["ЖК Очень Длинное Название Жилого Комплекса С Корпусом 5"]

    markup = build_jk_keyboard(complexes, page=0)
    button = markup.inline_keyboard[0][0]

    assert not button.text.startswith("ЖК ")
    assert len(button.text) <= JK_BUTTON_MAX_LEN
    assert button.text.endswith("…")


def test_main_menu_keyboard_shows_primary_actions() -> None:
    markup = build_main_menu_keyboard()

    assert markup.resize_keyboard is True
    assert markup.is_persistent is True
    assert [[button.text for button in row] for row in markup.keyboard] == [
        [MAIN_MENU_NEW_REQUEST, MAIN_MENU_STATUS]
    ]
