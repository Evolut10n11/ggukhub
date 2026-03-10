from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.telegram.bot import build_bot_commands
from app.telegram.handlers.dialog import _message_transport
from app.telegram.keyboards import MAIN_MENU_NEW_REQUEST, MAIN_MENU_STATUS


class _MessageStub:
    def __init__(self) -> None:
        self.from_user = SimpleNamespace(id=1, full_name="Test User", username=None)
        self.answers: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup: object | None = None) -> None:
        self.answers.append((text, reply_markup))


def test_build_bot_commands_exposes_start_new_and_status() -> None:
    commands = build_bot_commands()

    assert [(command.command, command.description) for command in commands] == [
        ("start", "Открыть бота"),
        ("new", "Новая заявка"),
        ("status", "Статус заявки"),
    ]


@pytest.mark.asyncio
async def test_message_transport_uses_main_menu_keyboard_for_plain_messages() -> None:
    message = _MessageStub()
    transport = _message_transport(message)

    await transport.send_text("Тест", None)

    assert len(message.answers) == 1
    _, reply_markup = message.answers[0]
    assert reply_markup is not None
    assert [[button.text for button in row] for row in reply_markup.keyboard] == [
        [MAIN_MENU_NEW_REQUEST, MAIN_MENU_STATUS]
    ]
