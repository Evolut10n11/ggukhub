from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any

from app.config import Settings
from app.core.services import AppServices
from app.max.client import MaxApiError, MaxBotClient
from app.max.keyboards import MaxKeyboardFactory
from app.max.routing import (
    MAX_COMMANDS,
    MaxBotIdentity,
    MaxRouteDecision,
    route_max_update,
    update_deduplication_key,
)
from app.telegram.dialog.models import DialogTransport
from app.telegram.dialog.service import DialogService

logger = logging.getLogger(__name__)

_DEDUPLICATION_WINDOW = 4096
_ACTIVE_GROUP_DIALOG_TTL_SECONDS = 30 * 60
_HELP_TEXT = (
    "Я помогу оформить обращение в управляющую компанию.\n\n"
    "Команды:\n"
    "/помощь — эта справка\n"
    "/авария — аварийное обращение\n"
    "/заявка — обычная заявка\n"
    "/домофон, /лифт, /уборка, /вода, /отопление — тематическая заявка"
)
_THEMATIC_COMMAND_TEXT = {
    "авария": "Аварийная ситуация в доме",
    "домофон": "Не работает домофон",
    "лифт": "Не работает лифт",
    "уборка": "Не выполнена уборка в доме",
    "вода": "Проблема с водоснабжением",
    "отопление": "Проблема с отоплением",
}


class _BufferedMaxTransport:
    """Collect all dialog output and emit one MAX message for one input event."""

    def __init__(
        self,
        *,
        client: MaxBotClient,
        chat_id: int,
        user_id: int,
        display_name: str | None,
        reply_to_mid: str | None,
    ) -> None:
        self.platform_user_id = user_id
        self.display_name = display_name
        self.platform = "max"
        self.platform_chat_id = chat_id
        self._client = client
        self._chat_id = chat_id
        self._reply_to_mid = reply_to_mid
        self._messages: list[tuple[str, Any | None]] = []

    async def send_text(self, text: str, reply_markup: Any | None) -> None:
        self._messages.append((text, reply_markup))

    async def clear_inline_keyboard(self) -> None:
        return None

    async def flush(self) -> None:
        if not self._messages:
            return
        text = "\n\n".join(part.strip() for part, _ in self._messages if part.strip())
        reply_markup = next(
            (markup for _, markup in reversed(self._messages) if markup is not None),
            None,
        )
        attachments = reply_markup if isinstance(reply_markup, list) else None
        logger.debug(
            "MAX response chat_id=%s parts=%s attachments=%s reply=%s",
            self._chat_id,
            len(self._messages),
            bool(attachments),
            bool(self._reply_to_mid),
        )
        kwargs: dict[str, Any] = {"attachments": attachments}
        if self._reply_to_mid:
            kwargs["reply_to_mid"] = self._reply_to_mid
        await self._client.send_message(self._chat_id, text, **kwargs)
        self._messages.clear()


class MaxPolling:
    """Long-polling loop for MAX Bot API."""

    def __init__(self, settings: Settings, services: AppServices) -> None:
        self._settings = settings
        self._services = services
        self._client = MaxBotClient(settings)
        self._kb = MaxKeyboardFactory(redirect_bot_url=settings.max_redirect_bot_url)
        self._marker: int | None = None
        self._running = False
        self._dialog_service: DialogService | None = None
        self._identity = MaxBotIdentity(settings.max_bot_id, settings.max_bot_username)
        self._seen_updates: OrderedDict[str, None] = OrderedDict()
        self._active_group_dialogs: dict[tuple[str, str], float] = {}

    def _get_dialog_service(self) -> DialogService:
        if self._dialog_service is None:
            self._dialog_service = DialogService(self._services, keyboard_factory=self._kb)
        return self._dialog_service

    def _get_operator_service(self):
        return getattr(self._services, "max_operator_service", None)

    async def start(self) -> None:
        try:
            me = await self._client.get_me()
        except Exception:
            if self._identity.user_id is None or not self._identity.username:
                raise
            logger.warning("MAX GET /me failed; using configured bot identity")
        else:
            self._identity = MaxBotIdentity(
                user_id=me.get("user_id") or self._identity.user_id,
                username=me.get("username") or self._identity.username,
            )
        logger.info("MAX bot started: user_id=%s", self._identity.user_id)
        try:
            await self._client.set_commands(
                [
                    *MAX_COMMANDS,
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
        deduplication_key = update_deduplication_key(update)
        if deduplication_key and not self._remember_update(deduplication_key):
            logger.debug("duplicate_update update_type=%s", update_type)
            return

        decision = route_max_update(update, self._identity)
        logger.debug("%s update_type=%s", decision.reason, update_type)
        if not decision.accepted:
            decision = await self._resume_active_group_dialog(update, decision)
            if not decision.accepted:
                return

        if decision.action == "message" or decision.action == "help":
            await self._handle_message(update, decision)
        elif decision.action == "callback":
            await self._handle_callback(update)
        elif decision.action == "bot_started":
            await self._handle_bot_started(update)

        await self._sync_active_group_dialog(update)

    async def _resume_active_group_dialog(
        self,
        update: dict[str, Any],
        decision: MaxRouteDecision,
    ) -> MaxRouteDecision:
        if decision.reason != "ignored_unaddressed_group_message":
            return decision

        context = self._group_dialog_context(update)
        if context is None:
            return decision

        last_activity = self._active_group_dialogs.get(context)
        if last_activity is None:
            return decision
        if time.monotonic() - last_activity > _ACTIVE_GROUP_DIALOG_TTL_SECONDS:
            self._active_group_dialogs.pop(context, None)
            return decision

        message = update.get("message", {})
        text = str(message.get("body", {}).get("text") or "").strip()
        logger.debug("accepted_active_group_dialog chat_id=%s user_id=%s", *context)
        return MaxRouteDecision(
            action="message",
            reason="accepted_active_group_dialog",
            text=text,
            chat_type=decision.chat_type,
            message_id=decision.message_id,
        )

    async def _sync_active_group_dialog(self, update: dict[str, Any]) -> None:
        context = self._group_dialog_context(update)
        if context is None:
            return

        _, platform_user_id = context
        service = self._get_dialog_service()
        if await service.has_active_dialog("max", int(platform_user_id)):
            self._active_group_dialogs[context] = time.monotonic()
        else:
            self._active_group_dialogs.pop(context, None)

    @staticmethod
    def _group_dialog_context(update: dict[str, Any]) -> tuple[str, str] | None:
        message = update.get("message", {})
        recipient = message.get("recipient", {})
        if str(recipient.get("chat_type") or "").casefold() != "chat":
            return None

        chat_id = recipient.get("chat_id")
        if update.get("update_type") == "message_callback":
            user_id = update.get("callback", {}).get("user", {}).get("user_id")
        else:
            user_id = message.get("sender", {}).get("user_id")
        if chat_id is None or user_id is None:
            return None
        return str(chat_id), str(user_id)

    def _remember_update(self, key: str) -> bool:
        if key in self._seen_updates:
            self._seen_updates.move_to_end(key)
            return False
        self._seen_updates[key] = None
        if len(self._seen_updates) > _DEDUPLICATION_WINDOW:
            self._seen_updates.popitem(last=False)
        return True

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
                "Режим оператора активен. Напишите /queue, чтобы увидеть открытые заявки.\n"
                f"Ваш MAX user_id: `{user_id}`",
            )
            return
        transport = self._make_transport(chat_id, user_id, display_name)
        service = self._get_dialog_service()
        await service.start(transport, include_welcome=True)
        await transport.flush()

    async def _handle_message(
        self, update: dict[str, Any], decision: MaxRouteDecision | None = None
    ) -> None:
        decision = decision or route_max_update(update, self._identity)
        if not decision.accepted:
            return
        message = update.get("message", {})
        sender = message.get("sender", {})
        user_id = sender.get("user_id")
        if not user_id:
            return

        body = message.get("body", {})
        text = decision.text
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

        reply_to_mid = decision.message_id if decision.chat_type == "chat" else None

        if decision.action == "help":
            await self._send_direct_message(chat_id, _HELP_TEXT, reply_to_mid=reply_to_mid)
            return

        if audio_url and self._services.speech.enabled:
            await self._handle_voice(
                chat_id, user_id, display_name, audio_url, reply_to_mid=reply_to_mid
            )
            return

        if not text:
            await self._send_direct_message(
                chat_id,
                "Я принимаю только текстовые и голосовые сообщения.",
                reply_to_mid=reply_to_mid,
            )
            return

        logger.info("MAX message accepted user=%s chat=%s reason=%s", user_id, chat_id, decision.reason)

        transport = self._make_transport(
            chat_id, user_id, display_name, reply_to_mid=reply_to_mid
        )
        service = self._get_dialog_service()

        if decision.command == "помощь":
            await self._send_direct_message(chat_id, _HELP_TEXT, reply_to_mid=reply_to_mid)
            return
        if decision.command == "заявка":
            await service.start(transport, include_welcome=False)
            await transport.flush()
            return
        if decision.command in _THEMATIC_COMMAND_TEXT:
            scenario_text = _THEMATIC_COMMAND_TEXT[decision.command]
            if decision.command_args:
                scenario_text = f"{scenario_text}: {decision.command_args}"
            await service.process_text(transport, scenario_text)
            await transport.flush()
            return

        if text.lower() in {"/id", "/myid", "/userid"}:
            await self._send_identity(chat_id, user_id)
            return

        operator_service = self._get_operator_service()
        if operator_service is not None:
            handled = await operator_service.handle_operator_message(chat_id, user_id, text)
            if handled:
                return

        # Handle commands
        if text.lower() in ("/start", "/new"):
            await service.start(transport, include_welcome=(text.lower() == "/start"))
            await transport.flush()
            return

        if text.lower() == "/status":
            await service.process_text(transport, "Статус заявки")
            await transport.flush()
            return

        if text.startswith("/"):
            await self._client.send_message(
                chat_id,
                "Неизвестная команда. Для жителей доступны /start, /new, /status, /id. Для оператора: /queue, /take, /reply, /close.",
            )
            return

        # Regular text
        await service.process_text(transport, text)
        await transport.flush()

    async def _send_identity(self, chat_id: int, user_id: int) -> None:
        await self._client.send_message(chat_id, f"Ваш MAX user_id: `{user_id}`")

    async def _handle_voice(
        self,
        chat_id: int,
        user_id: int,
        display_name: str | None,
        audio_url: str,
        *,
        reply_to_mid: str | None = None,
    ) -> None:
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
            await self._send_direct_message(
                chat_id,
                "Не получилось распознать голосовое. Напишите текстом.",
                reply_to_mid=reply_to_mid,
            )
            return

        text = recognized.strip()
        if not text:
            await self._send_direct_message(
                chat_id,
                "Не расслышала текст. Повторите или напишите сообщением.",
                reply_to_mid=reply_to_mid,
            )
            return

        transport = self._make_transport(
            chat_id, user_id, display_name, reply_to_mid=reply_to_mid
        )
        service = self._get_dialog_service()
        await service.process_text(transport, text, from_voice=True)
        await transport.flush()

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
        callback_message_id = message.get("body", {}).get("mid")
        chat_type = str(message.get("recipient", {}).get("chat_type") or "").casefold()
        transport = self._make_transport(
            chat_id,
            user_id,
            display_name,
            reply_to_mid=callback_message_id if chat_type == "chat" else None,
        )
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

        await transport.flush()

    async def _send_direct_message(
        self, chat_id: int, text: str, *, reply_to_mid: str | None = None
    ) -> None:
        kwargs: dict[str, Any] = {}
        if reply_to_mid:
            kwargs["reply_to_mid"] = reply_to_mid
        await self._client.send_message(chat_id, text, **kwargs)

    def _make_transport(
        self,
        chat_id: int,
        user_id: int,
        display_name: str | None,
        *,
        reply_to_mid: str | None = None,
    ) -> _BufferedMaxTransport:
        return _BufferedMaxTransport(
            client=self._client,
            chat_id=chat_id,
            user_id=user_id,
            display_name=display_name,
            reply_to_mid=reply_to_mid,
        )
