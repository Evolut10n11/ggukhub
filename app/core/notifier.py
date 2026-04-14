from __future__ import annotations

import logging

from app.config import Settings
from app.core.models import User
from app.max.notifier import MaxNotifier
from app.telegram.notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class UserNotifier:
    def __init__(self, settings: Settings):
        self._telegram = TelegramNotifier(settings.telegram_bot_token)
        self._max = MaxNotifier(settings)

    async def send_message(self, telegram_id: int, text: str) -> bool:
        return await self._telegram.send_message(telegram_id=telegram_id, text=text)

    async def send_user_message(self, user: User, text: str) -> bool:
        if user.platform == "max":
            if user.messenger_chat_id is None:
                logger.warning("MAX chat id is missing for user %s", user.id)
                return False
            return await self._max.send_message(chat_id=int(user.messenger_chat_id), text=text)
        return await self._telegram.send_message(telegram_id=user.platform_user_id, text=text)

    async def close(self) -> None:
        await self._telegram.close()
        await self._max.close()
