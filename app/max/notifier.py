from __future__ import annotations

import logging

from app.config import Settings
from app.max.client import MaxBotClient

logger = logging.getLogger(__name__)


class MaxNotifier:
    def __init__(self, settings: Settings):
        self._client = MaxBotClient(settings) if settings.max_enabled else None

    async def send_message(self, chat_id: int, text: str) -> bool:
        if self._client is None:
            return False
        try:
            await self._client.send_message(chat_id=chat_id, text=text)
            return True
        except Exception as error:
            logger.warning("Failed to send MAX notification: %s", error)
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
