from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from app.config import Settings
from app.core.services import AppServices
from app.max.client import MaxApiError, MaxBotClient

logger = logging.getLogger(__name__)


class MaxOperatorPolling:
    """Long-polling loop for the dedicated MAX Operator Bot."""

    def __init__(self, settings: Settings, services: AppServices) -> None:
        self._settings = settings
        self._services = services
        self._client = MaxBotClient(settings, token=settings.max_operator_bot_token)
        self._marker: int | None = None
        self._running = False

    def _get_operator_service(self):
        return getattr(self._services, "max_operator_service", None)

    @staticmethod
    async def _is_operator(operator_service: Any, user_id: int) -> bool:
        verdict = operator_service.is_operator(user_id)
        if inspect.isawaitable(verdict):
            verdict = await verdict
        return bool(verdict)

    async def start(self) -> None:
        me = await self._client.get_me()
        bot_name = me.get("name", me.get("username", "MAX Operator Bot"))
        logger.info("MAX Operator bot started: %s", bot_name)
        try:
            await self._client.set_commands(
                [
                    {"name": "start", "description": "Начать работу"},
                    {"name": "queue", "description": "Открытые заявки"},
                    {"name": "id", "description": "Показать мой user_id"},
                ]
            )
        except Exception:
            logger.warning("Failed to register MAX operator bot commands", exc_info=True)
        self._running = True
        while self._running:
            try:
                data = await self._client.get_updates(
                    marker=self._marker,
                    timeout=self._settings.max_polling_timeout,
                )
                updates = data.get("updates", [])
                new_marker = data.get("marker")
                if new_marker is not None:
                    self._marker = new_marker

                for update in updates:
                    try:
                        await self._handle_update(update)
                    except Exception:
                        logger.exception("Error handling MAX operator update: %s", update.get("update_type"))
            except MaxApiError as e:
                logger.error("MAX Operator API error during polling: %s", e)
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Unexpected error in MAX operator polling loop")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        self._running = False
        await self._client.close()

    async def _handle_update(self, update: dict[str, Any]) -> None:
        update_type = update.get("update_type")
        logger.debug("MAX operator update: type=%s data=%s", update_type, update)

        if update_type == "message_created":
            await self._handle_message(update)
        elif update_type == "message_callback":
            await self._handle_callback(update)
        elif update_type == "bot_started":
            await self._handle_bot_started(update)
        else:
            logger.debug("Ignoring MAX operator update type: %s", update_type)

    async def _handle_bot_started(self, update: dict[str, Any]) -> None:
        chat_id = update.get("chat_id")
        user = update.get("user", {})
        user_id = user.get("user_id")
        if not chat_id or not user_id:
            return
        logger.info("MAX operator bot_started from user=%s chat=%s", user_id, chat_id)

        operator_service = self._get_operator_service()
        if operator_service is not None and await self._is_operator(operator_service, user_id):
            await self._client.send_message(
                chat_id,
                "Режим оператора активен. Напишите /queue, чтобы увидеть открытые заявки.",
            )
        else:
            await self._client.send_message(
                chat_id,
                "Этот бот предназначен для операторов. Если вы оператор, отправьте свой номер телефона для авторизации.",
            )

    async def _handle_message(self, update: dict[str, Any]) -> None:
        message = update.get("message", {})
        sender = message.get("sender", {})
        user_id = sender.get("user_id")
        if not user_id:
            return

        body = message.get("body", {})
        text = body.get("text", "").strip()
        chat_id = message.get("recipient", {}).get("chat_id")
        if not chat_id:
            return

        if not text:
            await self._client.send_message(chat_id, "Отправьте текстовую команду.")
            return

        logger.info("MAX operator message from user=%s chat=%s text=%r", user_id, chat_id, text[:100])

        if text.lower() in {"/id", "/myid", "/userid"}:
            await self._client.send_message(chat_id, f"Ваш MAX user_id: `{user_id}`")
            return

        operator_service = self._get_operator_service()
        if operator_service is not None:
            handled = await operator_service.handle_operator_message(chat_id, user_id, text)
            if handled:
                return

        await self._client.send_message(
            chat_id,
            "Этот бот предназначен для операторов. Если вы оператор, отправьте свой номер телефона для авторизации.",
        )

    async def _handle_callback(self, update: dict[str, Any]) -> None:
        callback = update.get("callback", {})
        callback_id = callback.get("callback_id")
        payload = callback.get("payload", "")
        user = callback.get("user", {})
        user_id = user.get("user_id")
        message = update.get("message", {})
        chat_id = message.get("recipient", {}).get("chat_id")

        if not user_id or not chat_id:
            return

        if callback_id:
            try:
                await self._client.answer_callback(callback_id)
            except Exception:
                pass

        operator_service = self._get_operator_service()
        if operator_service is not None:
            await operator_service.handle_operator_callback(chat_id, user_id, payload)
