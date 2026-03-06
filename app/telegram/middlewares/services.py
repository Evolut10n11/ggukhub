from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware

from app.core.services import AppServices


class ServicesMiddleware(BaseMiddleware):
    def __init__(self, services: AppServices):
        super().__init__()
        self._services = services

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        data["services"] = self._services
        return await handler(event, data)

