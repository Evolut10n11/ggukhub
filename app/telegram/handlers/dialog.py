from __future__ import annotations

import io
import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, ErrorEvent, Message

from app.core.services import AppServices
from app.speech.client import SpeechToTextError
from app.telegram.constants import CATEGORY_LABELS
from app.telegram.dialog.models import DialogTransport
from app.telegram.dialog.service import DialogService
from app.telegram.keyboards import (
    MAIN_MENU_NEW_REQUEST,
    MAIN_MENU_STATUS,
    build_house_keyboard,
    build_jk_keyboard,
    build_main_menu_keyboard,
)

logger = logging.getLogger(__name__)

router = Router(name="dialog")


_cached_dialog_service: DialogService | None = None


def _dialog_service(services: AppServices) -> DialogService:
    global _cached_dialog_service
    if _cached_dialog_service is None:
        _cached_dialog_service = DialogService(services)
    return _cached_dialog_service


def _name_from_message(message: Message) -> str | None:
    if message.from_user is None:
        return None
    return message.from_user.full_name or message.from_user.username


def _name_from_callback(callback: CallbackQuery) -> str | None:
    return callback.from_user.full_name or callback.from_user.username


def _message_transport(message: Message) -> DialogTransport:
    if message.from_user is None:
        raise RuntimeError("Message sender is missing")

    async def _send_text(text: str, reply_markup: Any | None) -> None:
        await message.answer(text, reply_markup=reply_markup or build_main_menu_keyboard())

    async def _clear_inline_keyboard() -> None:
        return None

    return DialogTransport(
        platform_user_id=message.from_user.id,
        display_name=_name_from_message(message),
        send_text=_send_text,
        clear_inline_keyboard=_clear_inline_keyboard,
    )


def _callback_message(callback: CallbackQuery) -> Message | None:
    if isinstance(callback.message, Message):
        return callback.message
    return None


def _callback_transport(callback: CallbackQuery) -> DialogTransport:
    async def _send_text(text: str, reply_markup: Any | None) -> None:
        message = _callback_message(callback)
        if message is not None:
            await message.answer(text, reply_markup=reply_markup or build_main_menu_keyboard())
            return
        await callback.bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            reply_markup=reply_markup or build_main_menu_keyboard(),
        )

    async def _clear_inline_keyboard() -> None:
        message = _callback_message(callback)
        if message is None:
            return
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception as error:
            logger.debug("Cannot clear callback keyboard: %s", error)

    return DialogTransport(
        platform_user_id=callback.from_user.id,
        display_name=_name_from_callback(callback),
        send_text=_send_text,
        clear_inline_keyboard=_clear_inline_keyboard,
    )


async def _ack_callback(callback: CallbackQuery, text: str | None = None, *, show_alert: bool = False) -> None:
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except Exception as error:
        logger.debug("Callback ack skipped: %s", error)



async def _process_text_dialog(message: Message, services: AppServices, text: str, *, from_voice: bool = False) -> None:
    if message.from_user is None:
        return
    transport = _message_transport(message)
    await _dialog_service(services).process_text(transport, text, from_voice=from_voice)


async def _download_voice_bytes(message: Message) -> bytes:
    if message.voice is None:
        raise SpeechToTextError("Voice payload is missing")

    tg_file = await message.bot.get_file(message.voice.file_id)
    if not tg_file.file_path:
        raise SpeechToTextError("Cannot access Telegram file path")

    payload = io.BytesIO()
    await message.bot.download_file(tg_file.file_path, destination=payload)
    return payload.getvalue()


@router.message(CommandStart())
async def start_handler(message: Message, services: AppServices) -> None:
    if message.from_user is None:
        return
    await _dialog_service(services).start(_message_transport(message), include_welcome=True)


@router.message(Command("new"))
async def new_request_command_handler(message: Message, services: AppServices) -> None:
    if message.from_user is None:
        return
    await _dialog_service(services).start(_message_transport(message), include_welcome=False)


@router.message(Command("status"))
async def status_command_handler(message: Message, services: AppServices) -> None:
    if message.from_user is None:
        return
    await _process_text_dialog(message, services, MAIN_MENU_STATUS)


# ── JK callbacks ──


@router.callback_query(F.data.startswith("jk_page:"))
async def jk_page_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.data is None:
        return
    page_token = callback.data.split(":", 1)[1]
    if page_token == "stay":
        return

    page = int(page_token)
    message = _callback_message(callback)
    if message is not None:
        await message.edit_reply_markup(
            reply_markup=build_jk_keyboard(services.building_registry.complex_names, page=page)
        )


@router.callback_query(F.data.startswith("jk_pick:"))
async def jk_pick_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.data is None or callback.from_user is None:
        return

    names = services.building_registry.complex_names
    index = int(callback.data.split(":", 1)[1])
    if index < 0 or index >= len(names):
        await _callback_transport(callback).send_text("ЖК не найден", None)
        return

    await _dialog_service(services).select_housing_complex(
        _callback_transport(callback),
        names[index],
    )


@router.callback_query(F.data == "jk_standalone")
async def jk_standalone_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None:
        return
    await _dialog_service(services).show_standalone_houses(_callback_transport(callback))


@router.callback_query(F.data == "jk_unknown")
async def jk_unknown_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None:
        return
    await _dialog_service(services).mark_unknown_housing_complex(_callback_transport(callback))


# ── House callbacks ──


@router.callback_query(F.data.startswith("house_p:"))
async def house_page_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.data is None:
        return
    page_token = callback.data.split(":", 1)[1]
    if page_token == "stay":
        return
    page = int(page_token)
    await _dialog_service(services).paginate_houses(_callback_transport(callback), page)


@router.callback_query(F.data.startswith("house:"))
async def house_pick_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.data is None or callback.from_user is None:
        return
    index = int(callback.data.split(":", 1)[1])
    await _dialog_service(services).select_house(_callback_transport(callback), index)


# ── Entrance callbacks ──


@router.callback_query(F.data.startswith("ent:"))
async def entrance_pick_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.data is None or callback.from_user is None:
        return
    entrance = callback.data.split(":", 1)[1]
    await _dialog_service(services).select_entrance(_callback_transport(callback), entrance)


# ── Category callbacks ──


@router.callback_query(F.data == "cat_yes")
async def category_yes_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None:
        return
    await _dialog_service(services).confirm_category(_callback_transport(callback))


@router.callback_query(F.data == "cat_other")
async def category_other_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None:
        return
    await _dialog_service(services).request_manual_category(_callback_transport(callback))


@router.callback_query(F.data.startswith("cat_pick:"))
async def category_pick_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None or callback.data is None:
        return

    category = callback.data.split(":", 1)[1]
    if category not in CATEGORY_LABELS:
        await _callback_transport(callback).send_text(
            "Не удалось определить категорию. Напишите проблему еще раз, и я продолжу.",
            None,
        )
        return

    await _dialog_service(services).select_category(_callback_transport(callback), category)


# ── Report callbacks ──


@router.callback_query(F.data == "report_yes")
async def report_yes_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None:
        return
    await _dialog_service(services).confirm_report(_callback_transport(callback))


@router.callback_query(F.data == "report_edit")
async def report_edit_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None:
        return
    await _dialog_service(services).request_report_correction(_callback_transport(callback))


@router.callback_query(F.data == "new_report")
async def new_report_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None:
        return
    await _dialog_service(services).start(_callback_transport(callback), include_welcome=True)


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None:
        return
    await _dialog_service(services).start(_callback_transport(callback), include_welcome=True)


@router.callback_query(F.data == "back_to_menu_status")
async def back_to_menu_status_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None:
        return
    await _dialog_service(services).process_text(_callback_transport(callback), MAIN_MENU_STATUS)


# ── Phone callbacks ──


@router.callback_query(F.data == "phone_reuse_yes")
async def phone_reuse_yes_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None:
        return
    await _dialog_service(services).confirm_saved_phone(_callback_transport(callback))


@router.callback_query(F.data == "phone_reuse_other")
async def phone_reuse_other_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None:
        return
    await _dialog_service(services).request_new_phone(_callback_transport(callback))


@router.callback_query()
async def callback_fallback_handler(callback: CallbackQuery) -> None:
    await _ack_callback(callback, "Кнопка устарела. Напишите сообщение, и я продолжу.", show_alert=True)


# ── Message handlers ──


@router.message(F.voice)
async def voice_dialog_handler(message: Message, services: AppServices) -> None:
    if message.from_user is None or message.voice is None:
        return
    if not services.speech.enabled:
        await message.answer("Голосовые пока не подключены. Напишите, пожалуйста, текстом.")
        return

    await message.answer("Приняла голосовое. Распознаю и сразу продолжу оформление заявки.")
    try:
        voice_bytes = await _download_voice_bytes(message)
        recognized = await services.speech.transcribe_audio(
            audio_bytes=voice_bytes,
            filename="voice.ogg",
            content_type="audio/ogg",
        )
    except SpeechToTextError as error:
        logger.warning("Voice recognition failed: %s", error)
        await message.answer("Не получилось распознать голосовое. Напишите, пожалуйста, коротко текстом.")
        return
    except Exception as error:
        logger.exception("Voice handler failed: %s", error, exc_info=error)
        await message.answer("С голосовым возникла ошибка. Напишите, пожалуйста, текстом.")
        return

    text = recognized.strip()
    if not text:
        await message.answer("Не расслышала текст. Повторите голосом или напишите сообщением.")
        return

    await message.answer(f"Распознала так: «{text}».")
    await _process_text_dialog(message, services, text, from_voice=True)


@router.message(F.text)
async def text_dialog_handler(message: Message, services: AppServices) -> None:
    if message.from_user is None or message.text is None:
        return

    text = message.text.strip()
    if not text or text.startswith("/"):
        return
    if text == MAIN_MENU_NEW_REQUEST:
        await _dialog_service(services).start(_message_transport(message), include_welcome=False)
        return
    if text == MAIN_MENU_STATUS:
        await _process_text_dialog(message, services, text)
        return

    await _process_text_dialog(message, services, text)


@router.message()
async def unsupported_content_handler(message: Message) -> None:
    if message.from_user is None:
        return
    await message.answer("Я принимаю только текстовые и голосовые сообщения. Напишите или надиктуйте вашу проблему.")


@router.error()
async def error_handler(event: ErrorEvent) -> bool:
    logger.exception("Telegram handler error: %s", event.exception, exc_info=event.exception)

    if event.update.callback_query is not None:
        try:
            await event.update.callback_query.answer(
                "Не получилось обработать нажатие. Напишите сообщение, и я продолжу.",
                show_alert=True,
            )
        except Exception:
            logger.debug("Failed to send error callback answer", exc_info=True)

    if event.update.message is not None:
        try:
            await event.update.message.answer("Произошла ошибка. Напишите сообщение, и я продолжу оформление заявки.")
        except Exception:
            logger.debug("Failed to send error message reply", exc_info=True)

    return True
