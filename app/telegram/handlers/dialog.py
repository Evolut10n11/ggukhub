from __future__ import annotations

import asyncio
import io
import logging
from typing import Any, Awaitable

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, ErrorEvent, Message

from app.bitrix.client import BitrixClientError
from app.core.models import Report, User
from app.core.regulation import (
    REGULATION_VERSION,
    build_bitrix_audit_payload,
    build_report_composition_payload,
)
from app.core.schemas import ReportAuditCreate, ReportCreate, SessionPayload
from app.core.services import AppServices
from app.core.utils import build_address, compose_scope_key, normalize_phone, normalize_text
from app.speech.client import SpeechToTextError
from app.telegram.constants import (
    CATEGORY_LABELS,
    STEP_AWAITING_APT,
    STEP_AWAITING_CATEGORY_CONFIRM,
    STEP_AWAITING_CATEGORY_SELECT,
    STEP_AWAITING_ENTRANCE,
    STEP_AWAITING_HOUSE,
    STEP_AWAITING_JK,
    STEP_AWAITING_PHONE,
    STEP_AWAITING_PROBLEM,
    STEP_IDLE,
    UNKNOWN_JK_VALUE,
    WELCOME_TEXT,
)
from app.telegram.extractors import ExtractedReportContext, extract_report_context
from app.telegram.keyboards import (
    build_category_confirm_keyboard,
    build_category_select_keyboard,
    build_jk_keyboard,
)
from app.telegram.phrases import is_farewell_or_thanks, is_greeting

logger = logging.getLogger(__name__)

router = Router(name="dialog")
_user_locks: dict[int, asyncio.Lock] = {}
_bg_tasks: set[asyncio.Task[Any]] = set()


async def _upsert_user(services: AppServices, telegram_id: int, display_name: str | None) -> User:
    return await services.storage.upsert_user(telegram_id=telegram_id, name=display_name)


def _name_from_message(message: Message) -> str | None:
    if message.from_user is None:
        return None
    return message.from_user.full_name or message.from_user.username


def _name_from_callback(callback: CallbackQuery) -> str | None:
    return callback.from_user.full_name or callback.from_user.username


def _cleanup_optional_field(raw: str) -> str | None:
    value = raw.strip().lower()
    if value in {"", "-", "нет", "не знаю", "n/a"}:
        return None
    return raw.strip()


def _is_blank(value: str | None) -> bool:
    return value is None or not str(value).strip()


def _is_unknown_jk(value: str | None) -> bool:
    if _is_blank(value):
        return True
    return normalize_text(str(value)) == normalize_text(UNKNOWN_JK_VALUE)


def _merge_extracted_context(data: dict[str, Any], extracted: ExtractedReportContext) -> None:
    if extracted.jk and _is_unknown_jk(str(data.get("jk") or "")):
        data["jk"] = extracted.jk

    if extracted.house and _is_blank(str(data.get("house") or "")):
        data["house"] = extracted.house

    if extracted.entrance and _is_blank(str(data.get("entrance") or "")):
        data["entrance"] = extracted.entrance

    if extracted.apartment and _is_blank(str(data.get("apartment") or "")):
        data["apartment"] = extracted.apartment

    if extracted.phone:
        data["phone"] = extracted.phone


def _collected_fields_text(data: dict[str, Any], user_phone: str | None = None) -> str:
    jk = str(data.get("jk") or "").strip()
    house = str(data.get("house") or "").strip()
    entrance = str(data.get("entrance") or "").strip()
    apartment = str(data.get("apartment") or "").strip()
    phone = str(data.get("phone") or user_phone or "").strip()

    return (
        "По голосовому зафиксировала данные:\n"
        f"ЖК: {jk or 'не указан'}\n"
        f"Дом: {house or 'не указан'}\n"
        f"Подъезд: {entrance or 'не указан'}\n"
        f"Квартира: {apartment or 'не указана'}\n"
        f"Телефон: {phone or 'не указан'}"
    )


def _next_missing_step(data: dict[str, Any], user_phone: str | None) -> str:
    jk = str(data.get("jk") or "").strip()
    house = str(data.get("house") or "").strip()
    apartment = str(data.get("apartment") or "").strip()
    phone = str(data.get("phone") or user_phone or "").strip()
    problem_text = str(data.get("problem_text") or "").strip()
    entrance_value = data.get("entrance", "__missing__")

    if _is_unknown_jk(jk):
        return STEP_AWAITING_JK
    if not house:
        return STEP_AWAITING_HOUSE
    if entrance_value == "__missing__":
        return STEP_AWAITING_ENTRANCE
    if entrance_value is not None and not str(entrance_value).strip():
        return STEP_AWAITING_ENTRANCE
    if not apartment:
        return STEP_AWAITING_APT
    if not phone:
        return STEP_AWAITING_PHONE
    if not problem_text:
        return STEP_AWAITING_PROBLEM
    return STEP_AWAITING_CATEGORY_CONFIRM


def _is_yes_text(text: str) -> bool:
    value = normalize_text(text)
    return value in {"да", "верно", "подтверждаю", "ок", "окей", "yes"}


def _is_no_or_other_text(text: str) -> bool:
    value = normalize_text(text)
    return value in {"нет", "неверно", "другое", "другую", "выбрать другую", "other", "no"}


def _category_from_text(services: AppServices, text: str) -> str | None:
    value = normalize_text(text)
    if not value:
        return None

    categories = services.classifier.categories()
    if value in categories:
        return value

    text_map = {
        "water_off": {"нет воды", "без воды", "вода отключена", "воды нет"},
        "water_leak": {"протечка", "затопление", "течет", "потоп", "прорыв"},
        "electricity_off": {"нет света", "электричество", "свет отключен"},
        "elevator": {"лифт", "застряли в лифте"},
        "heating": {"отопление", "холодно", "батареи холодные"},
        "sewage": {"канализация", "засор", "воняет"},
        "intercom": {"домофон", "не открывает дверь"},
        "cleaning": {"уборка", "грязно", "мусор"},
        "other": {"другое", "другую", "иное"},
    }

    for code in categories:
        if value == normalize_text(services.classifier.label(code)):
            return code
        if value == normalize_text(CATEGORY_LABELS.get(code, "")):
            return code

    for code, variants in text_map.items():
        if code not in categories:
            continue
        if value in {normalize_text(token) for token in variants}:
            return code

    return None


async def _save_session(services: AppServices, user_id: int, step: str, data: dict[str, Any]) -> None:
    await services.storage.save_session(user_id=user_id, payload=SessionPayload(step=step, data=data))


def _callback_message(callback: CallbackQuery) -> Message | None:
    if isinstance(callback.message, Message):
        return callback.message
    return None


async def _send_callback_text(callback: CallbackQuery, text: str, reply_markup: Any | None = None) -> None:
    message = _callback_message(callback)
    if message is not None:
        await message.answer(text, reply_markup=reply_markup)
        return
    await callback.bot.send_message(chat_id=callback.from_user.id, text=text, reply_markup=reply_markup)


async def _ack_callback(callback: CallbackQuery, text: str | None = None, *, show_alert: bool = False) -> None:
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except Exception as error:
        logger.debug("Callback ack skipped: %s", error)


async def _store_audit_log(
    services: AppServices,
    *,
    report_id: int,
    stage: str,
    payload: dict[str, Any],
) -> None:
    try:
        await services.storage.create_report_audit(
            ReportAuditCreate(
                report_id=report_id,
                stage=stage,
                regulation_version=REGULATION_VERSION,
                payload=payload,
            )
        )
    except Exception as error:
        logger.warning("Report audit log save failed for report %s at stage %s: %s", report_id, stage, error)


def _user_lock(user_id: int) -> asyncio.Lock:
    lock = _user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock
    return lock


def _register_background_task(coro: Awaitable[Any]) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)

    def _on_done(done_task: asyncio.Task[Any]) -> None:
        _bg_tasks.discard(done_task)
        try:
            done_task.result()
        except Exception:
            logger.exception("Background task failed")

    task.add_done_callback(_on_done)


async def _clear_callback_keyboard(callback: CallbackQuery) -> None:
    message = _callback_message(callback)
    if message is None:
        return
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception as error:
        logger.debug("Cannot clear callback keyboard: %s", error)


async def _send_onboarding(message: Message, services: AppServices, *, include_welcome: bool) -> None:
    text = (
        WELCOME_TEXT
        if include_welcome
        else (
            "Через меня можно быстро отправить заявку в диспетчерскую — текстом или голосом.\n\n"
            "Сначала выберите ваш жилой комплекс:"
        )
    )
    await message.answer(text, reply_markup=build_jk_keyboard(services.housing_complexes, page=0))


def _build_report_summary(
    *,
    services: AppServices,
    report_id: int,
    category: str,
    jk: str | None,
    house: str,
    entrance: str | None,
    apartment: str,
) -> str:
    lines = [
        "Сводка по заявке:",
        f"Тип: {services.classifier.label(category)}",
        f"ЖК: {jk or 'не указан'}",
        f"Дом: {house}",
        f"Подъезд: {entrance or 'не указан'}",
        f"Квартира: {apartment}",
        f"Статус: создана (локальный №{report_id})",
    ]
    if services.bitrix_client.enabled:
        lines.append("Bitrix24: передаю заявку, номер пришлю отдельным сообщением.")
    else:
        lines.append("Bitrix24: интеграция сейчас выключена.")
    return "\n".join(lines)


async def _ask_category_confirmation(message: Message, services: AppServices, user_id: int, data: dict[str, Any]) -> None:
    auto_category = services.classifier.classify(str(data.get("problem_text") or ""))
    if auto_category == "other":
        llm_category = await services.llm_category.resolve(str(data.get("problem_text") or ""))
        if llm_category is not None:
            auto_category = llm_category
    data["auto_category"] = auto_category
    await _save_session(services, user_id, STEP_AWAITING_CATEGORY_CONFIRM, data)

    label = services.classifier.label(auto_category)
    await message.answer(
        f"Похоже, это категория заявки: «{label}». Подтвердите, пожалуйста. "
        "Если не уверены, нажмите «Выбрать другую».",
        reply_markup=build_category_confirm_keyboard(),
    )


async def _finalize_report(
    message: Message | None,
    services: AppServices,
    user: User,
    data: dict[str, Any],
    callback: CallbackQuery | None = None,
) -> None:
    jk_value = str(data.get("jk") or "").strip()
    jk = jk_value if jk_value and jk_value != UNKNOWN_JK_VALUE else None

    house = str(data.get("house") or "").strip()
    entrance = _cleanup_optional_field(str(data.get("entrance") or ""))
    apartment = str(data.get("apartment") or "").strip()
    phone = str(data.get("phone") or user.phone or "").strip()
    problem_text = str(data.get("problem_text") or "").strip()
    category = str(data.get("category") or data.get("auto_category") or "other")

    address = build_address(house=house, entrance=entrance, apartment=apartment)
    scope_key = compose_scope_key(jk=jk, category=category)

    report = await services.storage.create_report(
        ReportCreate(
            user_id=user.id,
            jk=jk,
            address=address,
            apt=apartment,
            phone=phone,
            category=category,
            text=problem_text,
            scope_key=scope_key,
        )
    )

    incident = await services.incidents.evaluate_report(report)
    normalized_report = {
        "local_report_id": report.id,
        "user_id": user.id,
        "telegram_id": user.telegram_id,
        "jk": jk,
        "address": address,
        "apartment": apartment,
        "phone": phone,
        "category": category,
        "scope_key": scope_key,
        "problem_text": problem_text,
    }
    composition_payload = build_report_composition_payload(
        source_session=data,
        normalized_report=normalized_report,
        category_label=services.classifier.label(category),
        is_mass_incident=incident.is_mass,
        incident_id=incident.incident_id,
    )
    await _store_audit_log(
        services,
        report_id=report.id,
        stage="report_created",
        payload=composition_payload,
    )

    standard_reply = await services.responder.report_created(local_id=report.id, bitrix_id=None)
    summary = _build_report_summary(
        services=services,
        report_id=report.id,
        category=category,
        jk=jk,
        house=house,
        entrance=entrance,
        apartment=apartment,
    )

    if incident.is_mass and incident.public_message:
        chunks = [incident.public_message, f"Номер заявки: {report.id}.", summary]
        reply = "\n\n".join(chunks)
    else:
        reply = f"{standard_reply}\n\n{summary}"

    if jk is None:
        reply += "\n\nЕсли сможете, дополнительно напишите ЖК — я добавлю в заявку."

    if message is not None:
        await message.answer(reply)
    elif callback is not None:
        await callback.bot.send_message(chat_id=callback.from_user.id, text=reply)

    if services.bitrix_client.enabled:
        _register_background_task(
            _sync_bitrix_ticket(
                services=services,
                report=report,
                user=user,
                is_mass_incident=incident.is_mass,
            )
        )


async def _sync_bitrix_ticket(
    *,
    services: AppServices,
    report: Report,
    user: User,
    is_mass_incident: bool,
) -> None:
    try:
        bitrix_id = await services.bitrix_client.create_ticket(report=report, user=user)
        await services.storage.set_report_bitrix_id(report.id, bitrix_id)
    except BitrixClientError as error:
        await _store_audit_log(
            services,
            report_id=report.id,
            stage="bitrix_sync_failed",
            payload=build_bitrix_audit_payload(
                bitrix_id=None,
                status="failed",
                error=str(error),
            ),
        )
        logger.warning("Bitrix ticket creation failed for report %s: %s", report.id, error)
        await services.notifier.send_message(
            telegram_id=user.telegram_id,
            text=(
                f"Заявка №{report.id} уже сохранена. "
                "Передачу в Bitrix24 уточняю вручную и вернусь с обновлением."
            ),
        )
        return

    await _store_audit_log(
        services,
        report_id=report.id,
        stage="bitrix_synced",
        payload=build_bitrix_audit_payload(
            bitrix_id=bitrix_id,
            status="synced",
        ),
    )

    if is_mass_incident:
        followup = f"Дополнительно: заявка №{report.id} передана в Bitrix24, номер {bitrix_id}."
    else:
        followup = f"Заявка №{report.id} передана в Bitrix24. Номер в Bitrix24: {bitrix_id}."
    await services.notifier.send_message(telegram_id=user.telegram_id, text=followup)


@router.message(CommandStart())
async def start_handler(message: Message, services: AppServices) -> None:
    if message.from_user is None:
        return

    user = await _upsert_user(services, message.from_user.id, _name_from_message(message))
    await _save_session(services, user.id, STEP_AWAITING_JK, {})
    await _send_onboarding(message, services, include_welcome=True)


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
        await message.edit_reply_markup(reply_markup=build_jk_keyboard(services.housing_complexes, page=page))


@router.callback_query(F.data.startswith("jk_pick:"))
async def jk_pick_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.data is None:
        return

    index = int(callback.data.split(":", 1)[1])
    if callback.from_user is None:
        return
    if index < 0 or index >= len(services.housing_complexes):
        await _send_callback_text(callback, "ЖК не найден")
        return

    user = await _upsert_user(services, callback.from_user.id, _name_from_callback(callback))
    session = await services.storage.get_session(user.id)
    data = dict(session.data)
    data["jk"] = services.housing_complexes[index]
    await _save_session(services, user.id, STEP_AWAITING_HOUSE, data)

    await _send_callback_text(callback, "Спасибо. Уточните, пожалуйста, дом.")


@router.callback_query(F.data == "jk_unknown")
async def jk_unknown_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None:
        return

    user = await _upsert_user(services, callback.from_user.id, _name_from_callback(callback))
    session = await services.storage.get_session(user.id)
    data = dict(session.data)
    data["jk"] = UNKNOWN_JK_VALUE
    await _save_session(services, user.id, STEP_AWAITING_HOUSE, data)

    await _send_callback_text(
        callback,
        "Поняла. Тогда подскажите адрес: дом, подъезд (если есть) и квартиру. Сначала — дом.",
    )


@router.callback_query(F.data == "cat_yes")
async def category_yes_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None:
        return

    user = await _upsert_user(services, callback.from_user.id, _name_from_callback(callback))
    async with _user_lock(user.id):
        session = await services.storage.get_session(user.id)
        if session.step != STEP_AWAITING_CATEGORY_CONFIRM:
            await _send_callback_text(callback, "Эта кнопка уже неактуальна. Напишите сообщение, и я продолжу оформление заявки.")
            return

        data = dict(session.data)
        data["category"] = str(data.get("auto_category") or "other")
        await _save_session(services, user.id, STEP_IDLE, {})
        await _clear_callback_keyboard(callback)
        await _finalize_report(_callback_message(callback), services, user, data, callback=callback)


@router.callback_query(F.data == "cat_other")
async def category_other_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None:
        return

    user = await _upsert_user(services, callback.from_user.id, _name_from_callback(callback))
    async with _user_lock(user.id):
        session = await services.storage.get_session(user.id)
        if session.step != STEP_AWAITING_CATEGORY_CONFIRM:
            await _send_callback_text(callback, "Эта кнопка уже неактуальна. Напишите сообщение, и я продолжу оформление заявки.")
            return

        data = dict(session.data)
        await _save_session(services, user.id, STEP_AWAITING_CATEGORY_SELECT, data)
        await _clear_callback_keyboard(callback)
        await _send_callback_text(callback, "Выберите подходящую категорию:", reply_markup=build_category_select_keyboard())


@router.callback_query(F.data.startswith("cat_pick:"))
async def category_pick_handler(callback: CallbackQuery, services: AppServices) -> None:
    await _ack_callback(callback)
    if callback.from_user is None or callback.data is None:
        return

    user = await _upsert_user(services, callback.from_user.id, _name_from_callback(callback))
    async with _user_lock(user.id):
        session = await services.storage.get_session(user.id)
        if session.step != STEP_AWAITING_CATEGORY_SELECT:
            await _send_callback_text(callback, "Эта кнопка уже неактуальна. Напишите сообщение, и я продолжу оформление заявки.")
            return

        category = callback.data.split(":", 1)[1]
        if category not in CATEGORY_LABELS:
            await _send_callback_text(callback, "Не удалось определить категорию. Напишите проблему еще раз, и я продолжу.")
            return

        data = dict(session.data)
        data["category"] = category
        await _save_session(services, user.id, STEP_IDLE, {})
        await _clear_callback_keyboard(callback)
        await _finalize_report(_callback_message(callback), services, user, data, callback=callback)


@router.callback_query()
async def callback_fallback_handler(callback: CallbackQuery) -> None:
    await _ack_callback(callback, "Кнопка устарела. Напишите сообщение, и я продолжу.", show_alert=True)


async def _process_text_dialog(message: Message, services: AppServices, text: str, *, from_voice: bool = False) -> None:
    user = await _upsert_user(services, message.from_user.id, _name_from_message(message))
    async with _user_lock(user.id):
        session = await services.storage.get_session(user.id)
        data = dict(session.data)
        step = session.step
        extracted = extract_report_context(text, services.housing_complexes)
        _merge_extracted_context(data, extracted)

        if extracted.phone and extracted.phone != user.phone:
            await services.storage.update_user_phone(user.id, extracted.phone)
            user.phone = extracted.phone

        if step == STEP_IDLE and is_farewell_or_thanks(text):
            await message.answer("Пожалуйста. Если понадобится помощь, просто напишите проблему — я сразу начну оформление заявки.")
            return

        if step == STEP_IDLE and is_greeting(text):
            await _save_session(services, user.id, STEP_AWAITING_JK, {})
            await _send_onboarding(message, services, include_welcome=False)
            return

        if step == STEP_IDLE:
            data["problem_text"] = text
            next_step = _next_missing_step(data, None if from_voice else user.phone)

            if next_step == STEP_AWAITING_JK:
                await _save_session(services, user.id, STEP_AWAITING_JK, data)
                await message.answer("Приняла обращение. Оформим заявку: сначала выберите, пожалуйста, ЖК.")
                await message.answer(
                    "Выберите, пожалуйста, ЖК:",
                    reply_markup=build_jk_keyboard(services.housing_complexes, page=0),
                )
                return

            if next_step == STEP_AWAITING_HOUSE:
                await _save_session(services, user.id, STEP_AWAITING_HOUSE, data)
                await message.answer("Приняла обращение. Уточните, пожалуйста, дом.")
                return

            if next_step == STEP_AWAITING_ENTRANCE:
                await _save_session(services, user.id, STEP_AWAITING_ENTRANCE, data)
                await message.answer("Уточните подъезд. Если не знаете, напишите «-».")
                return

            if next_step == STEP_AWAITING_APT:
                await _save_session(services, user.id, STEP_AWAITING_APT, data)
                await message.answer("Уточните номер квартиры.")
                return

            if next_step == STEP_AWAITING_PHONE:
                await _save_session(services, user.id, STEP_AWAITING_PHONE, data)
                await message.answer("Укажите телефон для связи (например, +7XXXXXXXXXX).")
                return

            if next_step == STEP_AWAITING_PROBLEM:
                await _save_session(services, user.id, STEP_AWAITING_PROBLEM, data)
                await message.answer("Опишите, пожалуйста, проблему в 1-2 предложениях.")
                return

            await message.answer(_collected_fields_text(data, None if from_voice else user.phone))
            await _ask_category_confirmation(message, services, user.id, data)
            return

        if (
            from_voice
            and step
            in {
                STEP_AWAITING_HOUSE,
                STEP_AWAITING_ENTRANCE,
                STEP_AWAITING_APT,
                STEP_AWAITING_PHONE,
                STEP_AWAITING_PROBLEM,
            }
        ):
            house = str(data.get("house") or "").strip()
            apartment = str(data.get("apartment") or "").strip()
            phone = str(data.get("phone") or "").strip()
            if house and apartment and phone:
                data["problem_text"] = text
                await message.answer(_collected_fields_text(data, None))
                await _ask_category_confirmation(message, services, user.id, data)
                return

        if step == STEP_AWAITING_JK:
            if extracted.jk:
                data["jk"] = extracted.jk
                if from_voice and not str(data.get("problem_text") or "").strip():
                    data["problem_text"] = text

                next_step = _next_missing_step(data, None if from_voice else user.phone)
                if next_step == STEP_AWAITING_CATEGORY_CONFIRM:
                    await message.answer(_collected_fields_text(data, None if from_voice else user.phone))
                    await _ask_category_confirmation(message, services, user.id, data)
                    return

                await _save_session(services, user.id, next_step, data)
                if next_step == STEP_AWAITING_HOUSE:
                    await message.answer(f"ЖК зафиксировала: {extracted.jk}. Уточните, пожалуйста, дом.")
                elif next_step == STEP_AWAITING_ENTRANCE:
                    await message.answer(f"ЖК зафиксировала: {extracted.jk}. Уточните подъезд. Если не знаете, напишите «-».")
                elif next_step == STEP_AWAITING_APT:
                    await message.answer(f"ЖК зафиксировала: {extracted.jk}. Уточните номер квартиры.")
                elif next_step == STEP_AWAITING_PHONE:
                    await message.answer(
                        f"ЖК зафиксировала: {extracted.jk}. Укажите телефон для связи (например, +7XXXXXXXXXX)."
                    )
                else:
                    await message.answer(f"ЖК зафиксировала: {extracted.jk}. Опишите, пожалуйста, проблему в 1-2 предложениях.")
                return

            reminder = "Выберите, пожалуйста, ЖК кнопками ниже."
            if services.speech.enabled:
                reminder += "\nГолосовые тоже поддерживаются: можете надиктовать проблему, а я уточню шаги."
            await message.answer(reminder, reply_markup=build_jk_keyboard(services.housing_complexes, 0))
            return

        if step == STEP_AWAITING_HOUSE:
            house_value = extracted.house if extracted.house else text
            data["house"] = house_value
            await _save_session(services, user.id, STEP_AWAITING_ENTRANCE, data)
            await message.answer("Укажите подъезд. Если не знаете, напишите «-».")
            return

        if step == STEP_AWAITING_ENTRANCE:
            entrance_input = extracted.entrance if extracted.entrance else text
            data["entrance"] = _cleanup_optional_field(entrance_input)
            await _save_session(services, user.id, STEP_AWAITING_APT, data)
            await message.answer("Укажите номер квартиры.")
            return

        if step == STEP_AWAITING_APT:
            apartment_value = extracted.apartment if extracted.apartment else text
            data["apartment"] = apartment_value
            if user.phone and not from_voice:
                data["phone"] = user.phone
                if str(data.get("problem_text") or "").strip():
                    await _ask_category_confirmation(message, services, user.id, data)
                else:
                    await _save_session(services, user.id, STEP_AWAITING_PROBLEM, data)
                    await message.answer("Опишите, пожалуйста, проблему в 1-2 предложениях.")
            else:
                await _save_session(services, user.id, STEP_AWAITING_PHONE, data)
                await message.answer("Укажите телефон для связи (например, +7XXXXXXXXXX).")
            return

        if step == STEP_AWAITING_PHONE:
            phone = extracted.phone or normalize_phone(text)
            if phone is None:
                await message.answer("Не удалось распознать номер. Напишите, пожалуйста, в формате +7XXXXXXXXXX.")
                return
            data["phone"] = phone
            await services.storage.update_user_phone(user.id, phone)
            if str(data.get("problem_text") or "").strip():
                await _ask_category_confirmation(message, services, user.id, data)
            else:
                await _save_session(services, user.id, STEP_AWAITING_PROBLEM, data)
                await message.answer("Спасибо. Теперь коротко опишите проблему.")
            return

        if step == STEP_AWAITING_PROBLEM:
            data["problem_text"] = text
            await _ask_category_confirmation(message, services, user.id, data)
            return

        if step == STEP_AWAITING_CATEGORY_CONFIRM:
            if _is_yes_text(text):
                data["category"] = str(data.get("auto_category") or "other")
                await _save_session(services, user.id, STEP_IDLE, {})
                await _finalize_report(message, services, user, data)
                return

            if _is_no_or_other_text(text):
                await _save_session(services, user.id, STEP_AWAITING_CATEGORY_SELECT, data)
                await message.answer("Выберите подходящую категорию:", reply_markup=build_category_select_keyboard())
                return

            await message.answer(
                "Подтвердите категорию: нажмите кнопку или напишите «да» / «другое»."
            )
            return

        if step == STEP_AWAITING_CATEGORY_SELECT:
            parsed_category = _category_from_text(services, text)
            if parsed_category is None:
                await message.answer("Выберите категорию кнопками ниже.", reply_markup=build_category_select_keyboard())
                return

            data["category"] = parsed_category
            await _save_session(services, user.id, STEP_IDLE, {})
            await _finalize_report(message, services, user, data)
            return

        await _save_session(services, user.id, STEP_AWAITING_JK, {})
        await message.answer(
            "Готова помочь с новой заявкой. Выберите, пожалуйста, ЖК:",
            reply_markup=build_jk_keyboard(services.housing_complexes, 0),
        )


async def _download_voice_bytes(message: Message) -> bytes:
    if message.voice is None:
        raise SpeechToTextError("Voice payload is missing")

    tg_file = await message.bot.get_file(message.voice.file_id)
    if not tg_file.file_path:
        raise SpeechToTextError("Cannot access Telegram file path")

    payload = io.BytesIO()
    await message.bot.download_file(tg_file.file_path, destination=payload)
    return payload.getvalue()


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

    await _process_text_dialog(message, services, text)


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
            pass

    if event.update.message is not None:
        try:
            await event.update.message.answer("Произошла ошибка. Напишите сообщение, и я продолжу оформление заявки.")
        except Exception:
            pass

    return True
