from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.config.settings import Settings
from app.core.buildings import BuildingRegistry, complex_key
from app.max.keyboards import MaxKeyboardFactory
from app.max.polling import MaxPolling
from app.telegram.dialog.service import DialogService
from app.telegram.handlers import dialog as telegram_dialog
from app.telegram.keyboards import build_jk_keyboard


@pytest.fixture
def registry() -> BuildingRegistry:
    return BuildingRegistry.from_file(
        Path(__file__).resolve().parents[1] / "data" / "housing_complexes.json"
    )


def _jk_buttons(names: list[str], platform: str) -> dict[str, str]:
    buttons = {}
    for page in range((len(names) + 7) // 8):
        if platform == "telegram":
            rows = build_jk_keyboard(names, page).inline_keyboard
            choices = [(button.text, button.callback_data) for row in rows for button in row]
        else:
            rows = MaxKeyboardFactory().jk_keyboard(names, page)[0]["payload"]["buttons"]
            choices = [(button["text"], button.get("payload", "")) for row in rows for button in row]
        buttons.update((label, payload) for label, payload in choices if payload.startswith("jk_select:"))
    return buttons


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_complex_buttons_keep_identity_when_registry_is_reordered(
    registry: BuildingRegistry, platform: str
) -> None:
    names = registry.complex_names
    buttons = _jk_buttons(names, platform)

    assert set(buttons) == set(names)
    assert buttons == _jk_buttons(list(reversed(names)), platform)
    assert all(len(payload.encode("utf-8")) <= 64 for payload in buttons.values())
    assert {registry.complex_name_for_key(payload.split(":", 1)[1]) for payload in buttons.values()} == set(names)
    assert "Еврокласс" in buttons
    assert "Гранд Комфорт" in buttons
    assert not {"Еврокласс-4", "Гранд Комфорт-2", "Гранд Комфорт-3"} & buttons.keys()


@pytest.mark.asyncio
async def test_telegram_selects_exact_complex_after_registry_reorder(
    registry: BuildingRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    callback_data = _jk_buttons(registry.complex_names, "telegram")["Еврокласс"]
    registry.complexes.reverse()
    service = Mock(spec=DialogService)
    transport = SimpleNamespace(send_text=AsyncMock())
    monkeypatch.setattr(telegram_dialog, "_dialog_service", lambda _: service)
    monkeypatch.setattr(telegram_dialog, "_callback_transport", lambda _: transport)
    callback = SimpleNamespace(data=callback_data, from_user=object(), answer=AsyncMock())

    await telegram_dialog.jk_select_handler(callback, SimpleNamespace(building_registry=registry))

    callback.answer.assert_awaited_once()
    service.select_housing_complex.assert_awaited_once_with(transport, "Еврокласс")
    service.start.assert_not_called()
    transport.send_text.assert_not_called()


_STALE_PAYLOADS = [
    "jk_pick:0",
    "jk_pick:garbage",
    "jk_select:unknown",
    f"jk_select:{complex_key('Еврокласс-4')}",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", _STALE_PAYLOADS)
async def test_telegram_stale_choice_refreshes_menu_without_touching_active_request(
    registry: BuildingRegistry, monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    service_getter = Mock()
    transport = SimpleNamespace(send_text=AsyncMock())
    monkeypatch.setattr(telegram_dialog, "_dialog_service", service_getter)
    monkeypatch.setattr(telegram_dialog, "_callback_transport", lambda _: transport)
    callback = SimpleNamespace(data=payload, from_user=object(), answer=AsyncMock())
    handler = telegram_dialog.jk_pick_handler if payload.startswith("jk_pick:") else telegram_dialog.jk_select_handler

    await handler(callback, SimpleNamespace(building_registry=registry))

    callback.answer.assert_awaited_once()
    service_getter.assert_not_called()
    transport.send_text.assert_awaited_once()
    text, keyboard = transport.send_text.call_args.args
    assert "обновлён" in text
    assert keyboard == build_jk_keyboard(registry.complex_names, page=0)


def _max_poller(registry: BuildingRegistry) -> MaxPolling:
    poller = MaxPolling(
        Settings(_env_file=None, max_redirect_bot_url=""),
        SimpleNamespace(building_registry=registry),
    )
    poller._dialog_service = Mock(spec=DialogService)
    poller._client = SimpleNamespace(answer_callback=AsyncMock(), send_message=AsyncMock())
    return poller


def _max_callback(payload: str) -> dict:
    return {
        "callback": {
            "callback_id": "cb-menu",
            "payload": payload,
            "user": {"user_id": 101, "name": "Житель"},
        },
        "message": {"recipient": {"chat_id": 202}},
    }


@pytest.mark.asyncio
async def test_max_selects_exact_complex_after_registry_reorder(registry: BuildingRegistry) -> None:
    payload = _jk_buttons(registry.complex_names, "max")["Еврокласс"]
    registry.complexes.reverse()
    poller = _max_poller(registry)

    await poller._handle_callback(_max_callback(payload))

    poller._client.answer_callback.assert_awaited_once_with("cb-menu")
    poller._dialog_service.select_housing_complex.assert_awaited_once()
    assert poller._dialog_service.select_housing_complex.call_args.args[1] == "Еврокласс"
    poller._dialog_service.start.assert_not_called()
    poller._client.send_message.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", _STALE_PAYLOADS)
async def test_max_stale_choice_refreshes_menu_without_touching_active_request(
    registry: BuildingRegistry, payload: str
) -> None:
    poller = _max_poller(registry)

    await poller._handle_callback(_max_callback(payload))

    poller._client.answer_callback.assert_awaited_once_with("cb-menu")
    assert poller._dialog_service.mock_calls == []
    poller._client.send_message.assert_awaited_once()
    call = poller._client.send_message.call_args
    assert call.args[0] == 202
    assert "обновлён" in call.args[1]
    assert call.kwargs["attachments"] == MaxKeyboardFactory().jk_keyboard(registry.complex_names, 0)
