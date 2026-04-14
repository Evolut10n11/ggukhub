from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import Settings
from app.core.services import AppServices
from app.max.client import MaxApiError, MaxBotClient
from app.max.keyboards import MaxKeyboardFactory
from app.telegram.dialog.models import DialogTransport
from app.telegram.dialog.service import DialogService

logger = logging.getLogger(__name__)


class MaxPolling:
    """Long-polling loop for MAX Bot API."""

    def __init__(self, settings: Settings, services: AppServices) -> None:
        self._settings = settings
        self._services = services
        self._client = MaxBotClient(settings)
        self._kb = MaxKeyboardFactory()
        self._marker: int | None = None
        self._running = False
        self._dialog_service: DialogService | None = None

    def _get_dialog_service(self) -> DialogService:
        if self._dialog_service is None:
            self._dialog_service = DialogService(self._services, keyboard_factory=self._kb)
        return self._dialog_service

    def _get_operator_service(self):
        return getattr(self._services, "max_operator_service", None)

    async def start(self) -> None:
        me = await self._client.get_me()
        bot_name = me.get("name", me.get("username", "MAX Bot"))
        logger.info("MAX bot started: %s", bot_name)
        try:
            await self._client.set_commands(
                [
                    {"name": "start", "description": "Начать работу с ботом"},
                    {"name": "new", "description": "Создать новую заявку"},
                    {"name": "status", "description": "Статус последней заявки"},
                    {"name": "id", "description": "Показать мой user_id"},
                ]
            )
        except Exception:
            logger.warning("Failed to register MAX bot commands", exc_info=True)
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
                        logger.exception("Error handling MAX update: %s", update.get("update_type"))
            except MaxApiError as e:
                logger.error("MAX API error during polling: %s", e)
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Unexpected error in MAX polling loop")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        self._running = False
        await self._client.close()

    async def _handle_update(self, update: dict[str, Any]) -> None:
        update_type = update.get("update_type")
        logger.debug("MAX update: type=%s data=%s", update_type, update)

        if update_type == "message_created":
            await self._handle_message(update)
        elif update_type == "message_callback":
            await self._handle_callback(update)
        elif update_type == "bot_started":
            await self._handle_bot_started(update)
        else:
            logger.debug("Ignoring MAX update type: %s", update_type)

    async def _handle_bot_started(self, update: dict[str, Any]) -> None:
        """Handle 'bot_started' event when user opens chat or presses Start."""
        chat_id = update.get("chat_id")
        user = update.get("user", {})
        user_id = user.get("user_id")
        if not chat_id or not user_id:
            return
        display_name = user.get("name")
        logger.info("MAX bot_started from user=%s chat=%s", user_id, chat_id)
        operator_service = self._get_operator_service()
        if operator_service is not None and operator_service.is_operator(user_id):
            await self._client.send_message(
                chat_id,
                "Режим оператора активен. Напишите /queue, чтобы увидеть открытые заявки. Чтобы узнать свой MAX user_id, отправьте /id.",
            )
            await self._send_identity(chat_id, user_id)
            return
        transport = self._make_transport(chat_id, user_id, display_name)
        service = self._get_dialog_service()
        await service.start(transport, include_welcome=True)

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

        display_name = sender.get("name")

        attachments = body.get("attachments", [])
        audio_url = None
        for att in attachments:
            att_type = att.get("type", "")
            if att_type in ("audio", "voice"):
                audio_url = att.get("payload", {}).get("url") or att.get("url")
                break

        if audio_url and self._services.speech.enabled:
            await self._handle_voice(chat_id, user_id, display_name, audio_url)
            return

        if not text:
            await self._client.send_message(chat_id, "Я принимаю только текстовые и голосовые сообщения.")
            return

        logger.info("MAX message from user=%s chat=%s text=%r", user_id, chat_id, text[:100])

        if text.lower() in {"/id", "/myid", "/userid"}:
            await self._send_identity(chat_id, user_id)
            return

        operator_service = self._get_operator_service()
        if operator_service is not None:
            handled = await operator_service.handle_operator_message(chat_id, user_id, text)
            if handled:
                return

        if text.lower() in ("/start", "/new"):
            transport = self._make_transport(chat_id, user_id, display_name)
            service = self._get_dialog_service()
            await service.start(transport, include_welcome=(text.lower() == "/start"))
            return

        if text.lower() == "/status":
            transport = self._make_transport(chat_id, user_id, display_name)
            service = self._get_dialog_service()
            await service.process_text(transport, "Статус заявки")
            return

        if text.startswith("/"):
            await self._client.send_message(
                chat_id,
                "Неизвестная команда. Для жителей доступны /start, /new, /status, /id. Для оператора: /queue, /take, /reply, /close.",
            )
            return

        transport = self._make_transport(chat_id, user_id, display_name)
        service = self._get_dialog_service()
        await service.process_text(transport, text)

    async def _send_identity(self, chat_id: int, user_id: int) -> None:
        await self._client.send_message(chat_id, f"Ваш MAX user_id: `{user_id}`")

    async def _handle_voice(self, chat_id: int, user_id: int, display_name: str | None, audio_url: str) -> None:
        await self._client.send_message(chat_id, "Приняла голосовое. Распознаю и сразу продолжу оформление заявки.")
        try:
            import httpx as _httpx

            async with _httpx.AsyncClient(timeout=30.0) as http:
                resp = await http.get(audio_url)
                resp.raise_for_status()
                audio_bytes = resp.content

            recognized = await self._services.speech.transcribe_audio(
                audio_bytes=audio_bytes,
                filename="voice.ogg",
                content_type="audio/ogg",
            )
        except Exception as e:
            logger.warning("MAX voice recognition failed: %s", e)
            await self._client.send_message(chat_id, "Не получилось распознать голосовое. Напишите текстом.")
            return

        text = recognized.strip()
        if not text:
            await self._client.send_message(chat_id, "Не расслышала текст. Повторите или напишите сообщением.")
            return

        await self._client.send_message(chat_id, f"Распознала так: «{text}».")
        transport = self._make_transport(chat_id, user_id, display_name)
        service = self._get_dialog_service()
        await service.process_text(transport, text, from_voice=True)

    async def _send_jk_page(self, transport: DialogTransport, page: int) -> None:
        await transport.send_text(
            "Через меня можно быстро отправить заявку в диспетчерскую.\n\n"
            "Сначала выберите ваш жилой комплекс:",
            self._kb.jk_keyboard(self._services.building_registry.complex_names, page=page),
        )

    async def _edit_jk_page(self, message_id: str, page: int) -> None:
        text = (
            "Через меня можно быстро отправить заявку в диспетчерскую.\n\n"
            "Сначала выберите ваш жилой комплекс:"
        )
        attachments = self._kb.jk_keyboard(self._services.building_registry.complex_names, page=page)
        await self._client.edit_message(message_id, text, attachments=attachments)

    async def _edit_house_page(self, message_id: str, user_id: int, page: int) -> None:
        service = self._get_dialog_service()
        houses = await service.get_house_list_for_user("max", user_id)
        if houses is None:
            return
        attachments = self._kb.house_keyboard(houses, page=page)
        await self._client.edit_message(message_id, "Выберите дом:", attachments=attachments)

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

        display_name = user.get("name")
        transport = self._make_transport(chat_id, user_id, display_name)
        service = self._get_dialog_service()

        if callback_id:
            try:
                await self._client.answer_callback(callback_id)
            except Exception:
                pass

        operator_service = self._get_operator_service()
        if operator_service is not None:
            handled = await operator_service.handle_operator_callback(chat_id, user_id, payload)
            if handled:
                return

        if payload.startswith("jk_pick:"):
            idx = int(payload.split(":", 1)[1])
            complex_names = self._services.building_registry.complex_names
            if 0 <= idx < len(complex_names):
                await service.select_housing_complex(transport, complex_names[idx])
        elif payload.startswith("jk_page:"):
            page_str = payload.split(":", 1)[1]
            if page_str != "stay":
                mid = message.get("body", {}).get("mid")
                if mid:
                    await self._edit_jk_page(mid, int(page_str))
                else:
                    await self._send_jk_page(transport, int(page_str))
        elif payload == "jk_standalone":
            await service.show_standalone_houses(transport)
        elif payload == "jk_unknown":
            await service.mark_unknown_housing_complex(transport)
        elif payload.startswith("house:"):
            idx = int(payload.split(":", 1)[1])
            await service.select_house(transport, idx)
        elif payload.startswith("house_p:"):
            page_str = payload.split(":", 1)[1]
            if page_str != "stay":
                mid = message.get("body", {}).get("mid")
                if mid:
                    await self._edit_house_page(mid, user_id, int(page_str))
                else:
                    await service.paginate_houses(transport, int(page_str))
        elif payload.startswith("ent:"):
            entrance = payload.split(":", 1)[1]
            await service.select_entrance(transport, entrance)
        elif payload == "cat_yes":
            await service.confirm_category(transport)
        elif payload == "cat_other":
            await service.request_manual_category(transport)
        elif payload.startswith("cat_pick:"):
            category = payload.split(":", 1)[1]
            await service.select_category(transport, category)
        elif payload == "report_yes":
            await service.confirm_report(transport)
        elif payload == "report_edit":
            await service.request_report_correction(transport)
        elif payload == "phone_reuse_yes":
            await service.confirm_saved_phone(transport)
        elif payload == "phone_reuse_other":
            await service.request_new_phone(transport)
        elif payload == "address_reuse_yes":
            await service.confirm_saved_address(transport)
        elif payload == "address_reuse_no":
            await service.reject_saved_address(transport)
        elif payload == "new_report":
            await service.start(transport, include_welcome=True)
        elif payload == "back_to_menu":
            await service.start(transport, include_welcome=True)
        elif payload == "back_to_menu_status":
            await service.process_text(transport, "Статус заявки")

    def _make_transport(self, chat_id: int, user_id: int, display_name: str | None) -> DialogTransport:
        client = self._client

        async def _send_text(text: str, reply_markup: Any | None) -> None:
            attachments = reply_markup if isinstance(reply_markup, list) else None
            logger.debug("MAX send to chat=%s attachments=%s text=%r", chat_id, bool(attachments), text[:80])
            await client.send_message(chat_id, text, attachments=attachments)

        async def _clear_inline_keyboard() -> None:
            pass

        return DialogTransport(
            platform_user_id=user_id,
            display_name=display_name,
            send_text=_send_text,
            clear_inline_keyboard=_clear_inline_keyboard,
            platform="max",
            platform_chat_id=chat_id,
        )
