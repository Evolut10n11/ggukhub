from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config.settings import Settings
from app.core.buildings import BuildingRegistry, ComplexInfo, HouseInfo
from app.max.keyboards import MaxKeyboardFactory
from app.max.polling import MaxPolling
from app.telegram.keyboards import (
    TelegramKeyboardFactory,
    build_category_confirm_keyboard,
    build_category_select_keyboard,
    build_entrance_keyboard,
    build_house_keyboard,
    build_jk_keyboard,
    build_phone_reuse_keyboard,
    build_report_confirm_keyboard,
)


def _max_rows(attachments: list[dict[str, object]]) -> list[list[tuple[str, str]]]:
    rows = attachments[0]["payload"]["buttons"]  # type: ignore[index]
    return [[(button["text"], button["payload"]) for button in row] for row in rows]  # type: ignore[index]


def _tg_rows(markup) -> list[list[tuple[str, str]]]:
    return [[(button.text, button.callback_data) for button in row] for row in markup.inline_keyboard]


class _DialogServiceStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def select_housing_complex(self, transport, complex_name: str) -> None:
        _ = transport
        self.calls.append(("select_housing_complex", complex_name))

    async def show_standalone_houses(self, transport) -> None:
        _ = transport
        self.calls.append(("show_standalone_houses", None))

    async def mark_unknown_housing_complex(self, transport) -> None:
        _ = transport
        self.calls.append(("mark_unknown_housing_complex", None))

    async def select_house(self, transport, idx: int) -> None:
        _ = transport
        self.calls.append(("select_house", idx))

    async def paginate_houses(self, transport, page: int) -> None:
        _ = transport
        self.calls.append(("paginate_houses", page))

    async def select_entrance(self, transport, entrance: str) -> None:
        _ = transport
        self.calls.append(("select_entrance", entrance))

    async def confirm_category(self, transport) -> None:
        _ = transport
        self.calls.append(("confirm_category", None))

    async def request_manual_category(self, transport) -> None:
        _ = transport
        self.calls.append(("request_manual_category", None))

    async def select_category(self, transport, category: str) -> None:
        _ = transport
        self.calls.append(("select_category", category))

    async def confirm_report(self, transport) -> None:
        _ = transport
        self.calls.append(("confirm_report", None))

    async def request_report_correction(self, transport) -> None:
        _ = transport
        self.calls.append(("request_report_correction", None))

    async def confirm_saved_phone(self, transport) -> None:
        _ = transport
        self.calls.append(("confirm_saved_phone", None))

    async def request_new_phone(self, transport) -> None:
        _ = transport
        self.calls.append(("request_new_phone", None))

    async def start(self, transport, *, include_welcome: bool) -> None:
        _ = transport
        self.calls.append(("start", include_welcome))

    async def process_text(self, transport, text: str, from_voice: bool = False) -> None:
        _ = transport, from_voice
        self.calls.append(("process_text", text))


class _MaxClientStub:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []
        self.answered_callbacks: list[str] = []

    async def send_message(self, chat_id: int, text: str, *, attachments=None, format: str = "markdown") -> dict[str, object]:
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "attachments": attachments,
                "format": format,
            }
        )
        return {"success": True}

    async def answer_callback(self, callback_id: str, *, notification: str | None = None) -> dict[str, object]:
        _ = notification
        self.answered_callbacks.append(callback_id)
        return {"success": True}


def test_max_shared_inline_keyboards_match_telegram() -> None:
    max_factory = MaxKeyboardFactory()
    telegram_factory = TelegramKeyboardFactory()

    complexes = [f"Complex {index}" for index in range(10)]
    houses = [HouseInfo(address=f"Дом {index}", entrances=4, apartments=20) for index in range(10)]

    assert _max_rows(max_factory.jk_keyboard(complexes, page=0)) == _tg_rows(build_jk_keyboard(complexes, page=0))
    assert _max_rows(max_factory.jk_keyboard(complexes, page=1)) == _tg_rows(build_jk_keyboard(complexes, page=1))
    assert _max_rows(max_factory.house_keyboard(houses, page=0)) == _tg_rows(build_house_keyboard(houses, page=0))
    assert _max_rows(max_factory.house_keyboard(houses, page=1)) == _tg_rows(build_house_keyboard(houses, page=1))
    assert _max_rows(max_factory.entrance_keyboard(6)) == _tg_rows(build_entrance_keyboard(6))
    assert _max_rows(max_factory.category_confirm_keyboard()) == _tg_rows(build_category_confirm_keyboard())
    assert _max_rows(max_factory.category_select_keyboard()) == _tg_rows(build_category_select_keyboard())
    assert _max_rows(max_factory.report_confirm_keyboard()) == _tg_rows(build_report_confirm_keyboard())
    assert _max_rows(max_factory.phone_reuse_keyboard("+79990001122")) == _tg_rows(build_phone_reuse_keyboard("+79990001122"))
    assert _max_rows(max_factory.new_report_keyboard()) == _tg_rows(telegram_factory.new_report_keyboard())
    assert _max_rows(max_factory.back_to_menu_keyboard()) == _tg_rows(telegram_factory.back_to_menu_keyboard())


@pytest.mark.asyncio
async def test_max_jk_page_callback_sends_requested_page_keyboard() -> None:
    settings = Settings(telegram_bot_token="test-token", max_bot_token="max-token")
    registry = BuildingRegistry(
        complexes=[ComplexInfo(name=f"Complex {index}") for index in range(18)],
        standalone_houses=[],
    )
    services = SimpleNamespace(building_registry=registry)
    poller = MaxPolling(settings, services)  # type: ignore[arg-type]
    poller._dialog_service = _DialogServiceStub()  # type: ignore[assignment]
    poller._client = _MaxClientStub()  # type: ignore[assignment]

    update = {
        "callback": {
            "callback_id": "cb-1",
            "payload": "jk_page:1",
            "user": {"user_id": 101, "name": "Tester"},
        },
        "message": {"recipient": {"chat_id": 202}},
    }

    await poller._handle_callback(update)

    assert poller._client.answered_callbacks == ["cb-1"]  # type: ignore[attr-defined]
    assert len(poller._client.sent_messages) == 1  # type: ignore[attr-defined]

    sent = poller._client.sent_messages[0]  # type: ignore[attr-defined]
    assert sent["chat_id"] == 202
    assert "жилой комплекс" in str(sent["text"])
    assert sent["attachments"] == MaxKeyboardFactory().jk_keyboard(registry.complex_names, page=1)


@pytest.mark.asyncio
async def test_max_callback_routes_match_expected_dialog_actions() -> None:
    settings = Settings(telegram_bot_token="test-token", max_bot_token="max-token")
    registry = BuildingRegistry(
        complexes=[ComplexInfo(name=f"Complex {index}") for index in range(3)],
        standalone_houses=[],
    )
    services = SimpleNamespace(building_registry=registry)
    poller = MaxPolling(settings, services)  # type: ignore[arg-type]
    poller._dialog_service = _DialogServiceStub()  # type: ignore[assignment]
    poller._client = _MaxClientStub()  # type: ignore[assignment]

    cases = [
        ("jk_pick:1", ("select_housing_complex", "Complex 1")),
        ("jk_standalone", ("show_standalone_houses", None)),
        ("jk_unknown", ("mark_unknown_housing_complex", None)),
        ("house:2", ("select_house", 2)),
        ("house_p:3", ("paginate_houses", 3)),
        ("ent:4", ("select_entrance", "4")),
        ("cat_yes", ("confirm_category", None)),
        ("cat_other", ("request_manual_category", None)),
        ("cat_pick:complaint", ("select_category", "complaint")),
        ("report_yes", ("confirm_report", None)),
        ("report_edit", ("request_report_correction", None)),
        ("phone_reuse_yes", ("confirm_saved_phone", None)),
        ("phone_reuse_other", ("request_new_phone", None)),
        ("new_report", ("start", True)),
        ("back_to_menu", ("start", True)),
        ("back_to_menu_status", ("process_text", "Статус заявки")),
    ]

    for index, (payload, expected) in enumerate(cases, start=1):
        before = len(poller._dialog_service.calls)  # type: ignore[attr-defined]
        await poller._handle_callback(
            {
                "callback": {
                    "callback_id": f"cb-{index}",
                    "payload": payload,
                    "user": {"user_id": 101, "name": "Tester"},
                },
                "message": {"recipient": {"chat_id": 202}},
            }
        )
        assert poller._dialog_service.calls[before] == expected  # type: ignore[attr-defined]
