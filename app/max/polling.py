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

    async def start(self) -> None:
        me = await self._client.get_me()
        bot_name = me.get("name", me.get("username", "MAX Bot"))
        logger.info("MAX bot started: %s", bot_name)
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
        """Handle 'bot_started' event — user pressed Start or opened chat for first time."""
        chat_id = update.get("chat_id")
        user = update.get("user", {})
        user_id = user.get("user_id")
        if not chat_id or not user_id:
            return
        display_name = user.get("name")
        logger.info("MAX bot_started from user=%s chat=%s", user_id, chat_id)
        transport = self._make_transport(chat_id, user_id, display_name)
        service = DialogService(self._services, keyboard_factory=self._kb)
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

        # Check for voice/audio attachments
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

        # Handle /start
        if text.lower() in ("/start", "/new"):
            transport = self._make_transport(chat_id, user_id, display_name)
            service = DialogService(self._services, keyboard_factory=self._kb)
            await service.start(transport, include_welcome=(text.lower() == "/start"))
            return

        # Regular text
        transport = self._make_transport(chat_id, user_id, display_name)
        service = DialogService(self._services, keyboard_factory=self._kb)
        await service.process_text(transport, text)

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
        service = DialogService(self._services, keyboard_factory=self._kb)
        await service.process_text(transport, text, from_voice=True)

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
        service = DialogService(self._services, keyboard_factory=self._kb)

        # Acknowledge callback
        if callback_id:
            try:
                await self._client.answer_callback(callback_id)
            except Exception:
                pass

        # Route callback by payload prefix (same as Telegram callback_data)
        if payload.startswith("jk_pick:"):
            idx = int(payload.split(":", 1)[1])
            complex_names = self._services.building_registry.complex_names
            if 0 <= idx < len(complex_names):
                await service.select_housing_complex(transport, complex_names[idx])
        elif payload.startswith("jk_page:"):
            page_str = payload.split(":", 1)[1]
            if page_str != "stay":
                await service.start(transport, include_welcome=False)
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
        elif payload == "new_report":
            await service.start(transport, include_welcome=True)

    def _make_transport(self, chat_id: int, user_id: int, display_name: str | None) -> DialogTransport:
        client = self._client

        async def _send_text(text: str, reply_markup: Any | None) -> None:
            attachments = reply_markup if isinstance(reply_markup, list) else None
            logger.debug("MAX send to chat=%s attachments=%s text=%r", chat_id, bool(attachments), text[:80])
            await client.send_message(chat_id, text, attachments=attachments)

        async def _clear_inline_keyboard() -> None:
            pass  # MAX doesn't require explicit keyboard clearing

        return DialogTransport(
            platform_user_id=user_id,
            display_name=display_name,
            send_text=_send_text,
            clear_inline_keyboard=_clear_inline_keyboard,
        )
