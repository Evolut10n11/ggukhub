from __future__ import annotations

import logging

from aiogram import Bot

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, token: str):
        self._token = token
        self._bot: Bot | None = Bot(token=token) if token else None

    async def send_message(self, telegram_id: int, text: str) -> bool:
        if self._bot is None:
            return False
        try:
            await self._bot.send_message(chat_id=telegram_id, text=text)
            return True
        except Exception as error:
            logger.warning("Failed to send telegram notification: %s", error)
            return False

    async def close(self) -> None:
        if self._bot is not None:
            await self._bot.session.close()

