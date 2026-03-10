from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.core.enums import BitrixSyncStatus, ReportAuditStage
from app.core.models import Report, User
from app.core.regulation import REGULATION_VERSION, build_bitrix_audit_payload, build_report_composition_payload
from app.core.schemas import ReportAuditCreate, ReportCreate, ReportLookupResult, SessionPayload
from app.core.utils import build_address, compose_scope_key, normalize_phone, normalize_text
from app.telegram.constants import CATEGORY_LABELS, UNKNOWN_JK_VALUE, WELCOME_TEXT
from app.telegram.dialog.classification import DialogCategoryService
from app.telegram.dialog.finalization import DialogReportFinalizer
from app.telegram.dialog.formatters import (
    ReportReviewView,
    build_report_review,
    build_resume_prompt,
    build_saved_phone_prompt,
)
from app.telegram.dialog.models import (
    ClassificationResult,
    DialogSessionData,
    DialogSnapshot,
    DialogStep,
    DialogTransport,
    FinalizedReportDraft,
)
from app.telegram.dialog.status_service import DialogReportLookupService
from app.telegram.dialog.problem_validation import problem_text_rejection_message, validate_problem_text
from app.telegram.dialog.state_machine import (
    category_from_text,
    cleanup_optional_field,
    collected_fields_text,
    dialog_step,
    is_report_status_request,
    is_no_or_other_text,
    is_saved_phone_accept_text,
    is_saved_phone_reject_text,
    is_unknown_jk,
    is_yes_text,
    merge_extracted_context,
    next_missing_step,
)
from app.telegram.extractors import ExtractedReportContext, extract_report_context
from app.telegram.keyboards import (
    build_category_confirm_keyboard,
    build_category_select_keyboard,
    build_jk_keyboard,
    build_phone_reuse_keyboard,
    build_report_confirm_keyboard,
)
from app.telegram.phrases import is_farewell_or_thanks, is_greeting

if TYPE_CHECKING:
    from app.core.services import AppServices

logger = logging.getLogger(__name__)


class DialogService:
    def __init__(self, services: AppServices):
        self._services = services
        self._runtime = services.dialog_runtime
        self._category_service = DialogCategoryService(services.classifier, services.llm_category)
        self._report_lookup_service = DialogReportLookupService(services.storage, services.classifier.label)
        self._report_finalizer = DialogReportFinalizer(
            storage=services.storage,
            incidents=services.incidents,
            responder=services.responder,
            bitrix_service=services.bitrix_service,
            notifier=services.notifier,
            label_resolver=services.classifier.label,
        )

    async def start(self, transport: DialogTransport, *, include_welcome: bool) -> None:
        user = await self._upsert_user(transport.telegram_id, transport.display_name)
        await self._save_snapshot(user.id, DialogStep.AWAITING_JK, DialogSessionData())
        await self._send_onboarding(transport, include_welcome=include_welcome)

    async def select_housing_complex(self, transport: DialogTransport, complex_name: str) -> None:
        user = await self._upsert_user(transport.telegram_id, transport.display_name)
        snapshot = await self._load_snapshot(user.id)
        data = snapshot.data.model_copy(deep=True)
        data.jk = complex_name
        await self._save_snapshot(user.id, DialogStep.AWAITING_HOUSE, data)
        await transport.send_text("Спасибо. Уточните, пожалуйста, дом.", None)

    async def mark_unknown_housing_complex(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.telegram_id, transport.display_name)
        snapshot = await self._load_snapshot(user.id)
        data = snapshot.data.model_copy(deep=True)
        data.jk = UNKNOWN_JK_VALUE
        await self._save_snapshot(user.id, DialogStep.AWAITING_HOUSE, data)
        await transport.send_text(
            "Поняла. Тогда подскажите адрес: дом, подъезд (если есть) и квартиру. Сначала — дом.",
            None,
        )

    async def confirm_category(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.telegram_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_CATEGORY_CONFIRM:
                await transport.send_text(
                    "Эта кнопка уже неактуальна. Напишите сообщение, и я продолжу оформление заявки.",
                    None,
                )
                return

            data = snapshot.data.model_copy(deep=True)
            data.category = str(data.auto_category or "other")
            await transport.clear_inline_keyboard()
            await self._send_report_confirmation(transport, user.id, data)

    async def request_manual_category(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.telegram_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_CATEGORY_CONFIRM:
                await transport.send_text(
                    "Эта кнопка уже неактуальна. Напишите сообщение, и я продолжу оформление заявки.",
                    None,
                )
                return

            await self._save_snapshot(user.id, DialogStep.AWAITING_CATEGORY_SELECT, snapshot.data)
            await transport.clear_inline_keyboard()
            await transport.send_text(
                "Выберите подходящую категорию:",
                build_category_select_keyboard(),
            )

    async def select_category(self, transport: DialogTransport, category: str) -> None:
        user = await self._upsert_user(transport.telegram_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_CATEGORY_SELECT:
                await transport.send_text(
                    "Эта кнопка уже неактуальна. Напишите сообщение, и я продолжу оформление заявки.",
                    None,
                )
                return

            if category not in CATEGORY_LABELS:
                await transport.send_text(
                    "Не удалось определить категорию. Напишите проблему еще раз, и я продолжу.",
                    None,
                )
                return

            data = snapshot.data.model_copy(deep=True)
            data.category = category
            await transport.clear_inline_keyboard()
            await self._send_report_confirmation(transport, user.id, data)

    async def confirm_saved_phone(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.telegram_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_PHONE_REUSE_CONFIRM:
                await transport.send_text(
                    "Эта кнопка уже неактуальна. Напишите сообщение, и я продолжу оформление заявки.",
                    None,
                )
                return

            await transport.clear_inline_keyboard()
            if not user.phone:
                await self._save_snapshot(user.id, DialogStep.AWAITING_PHONE, snapshot.data)
                await transport.send_text(
                    "Не нашла сохраненный номер. Укажите телефон для связи в формате +7XXXXXXXXXX.",
                    None,
                )
                return

            data = snapshot.data.model_copy(deep=True)
            data.phone = user.phone
            await self._continue_after_problem_capture(transport, user, data, from_voice=False)

    async def request_new_phone(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.telegram_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_PHONE_REUSE_CONFIRM:
                await transport.send_text(
                    "Эта кнопка уже неактуальна. Напишите сообщение, и я продолжу оформление заявки.",
                    None,
                )
                return

            await self._save_snapshot(user.id, DialogStep.AWAITING_PHONE, snapshot.data)
            await transport.clear_inline_keyboard()
            await transport.send_text("Укажите телефон для связи (например, +7XXXXXXXXXX).", None)

    async def confirm_report(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.telegram_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_REPORT_CONFIRM:
                await transport.send_text(
                    "Эта кнопка уже неактуальна. Напишите сообщение, и я продолжу оформление заявки.",
                    None,
                )
                return

            await self._save_snapshot(user.id, DialogStep.IDLE, DialogSessionData())
            await transport.clear_inline_keyboard()
            await self._finalize_report(transport, user, snapshot.data)

    async def request_report_correction(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.telegram_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_REPORT_CONFIRM:
                await transport.send_text(
                    "Эта кнопка уже неактуальна. Напишите сообщение, и я продолжу оформление заявки.",
                    None,
                )
                return

            await self._save_snapshot(user.id, DialogStep.AWAITING_REPORT_CORRECTION, snapshot.data)
            await transport.clear_inline_keyboard()
            await transport.send_text(
                "Напишите, что нужно исправить. Можно одним сообщением: адрес, телефон, описание проблемы или категорию. Потом я еще раз покажу сводку.",
                None,
            )

    async def process_text(self, transport: DialogTransport, text: str, *, from_voice: bool = False) -> None:
        user = await self._upsert_user(transport.telegram_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if is_report_status_request(text):
                await self._handle_report_status_request(transport, user, snapshot)
                return

            extracted = extract_report_context(text, self._services.housing_complexes)
            data = merge_extracted_context(snapshot.data, extracted)

            await self._sync_extracted_phone(user, extracted)
            if extracted.phone:
                user.phone = extracted.phone

            if snapshot.step == DialogStep.IDLE and is_farewell_or_thanks(text):
                await transport.send_text(
                    "Пожалуйста. Если понадобится помощь, просто напишите проблему — я сразу начну оформление заявки.",
                    None,
                )
                return

            if snapshot.step == DialogStep.IDLE and is_greeting(text):
                await self._save_snapshot(user.id, DialogStep.AWAITING_JK, DialogSessionData())
                await self._send_onboarding(transport, include_welcome=False)
                return

            if snapshot.step == DialogStep.IDLE:
                await self._handle_idle_step(transport, user, text, data, from_voice=from_voice)
                return

            if (
                from_voice
                and snapshot.step
                in {
                    DialogStep.AWAITING_HOUSE,
                    DialogStep.AWAITING_ENTRANCE,
                    DialogStep.AWAITING_APARTMENT,
                    DialogStep.AWAITING_PHONE,
                    DialogStep.AWAITING_PROBLEM,
                }
            ):
                if data.house and data.apartment and data.phone:
                    if not await self._try_capture_problem_text(
                        transport,
                        user.id,
                        data,
                        text,
                        retry_step=DialogStep.AWAITING_PROBLEM,
                    ):
                        return
                    await transport.send_text(collected_fields_text(data, None), None)
                    await self._continue_after_problem_capture(transport, user, data, from_voice=from_voice)
                    return

            step_handlers = {
                DialogStep.AWAITING_JK: self._handle_awaiting_jk,
                DialogStep.AWAITING_HOUSE: self._handle_awaiting_house,
                DialogStep.AWAITING_ENTRANCE: self._handle_awaiting_entrance,
                DialogStep.AWAITING_APARTMENT: self._handle_awaiting_apartment,
                DialogStep.AWAITING_PHONE: self._handle_awaiting_phone,
                DialogStep.AWAITING_PROBLEM: self._handle_awaiting_problem,
                DialogStep.AWAITING_PHONE_REUSE_CONFIRM: self._handle_awaiting_phone_reuse_confirm,
                DialogStep.AWAITING_CATEGORY_CONFIRM: self._handle_awaiting_category_confirm,
                DialogStep.AWAITING_CATEGORY_SELECT: self._handle_awaiting_category_select,
                DialogStep.AWAITING_REPORT_CONFIRM: self._handle_awaiting_report_confirm,
                DialogStep.AWAITING_REPORT_CORRECTION: self._handle_awaiting_report_correction,
            }
            handler = step_handlers.get(snapshot.step)
            if handler is None:
                await self._reset_to_new_request(transport, user.id)
                return

            await handler(
                transport=transport,
                user=user,
                text=text,
                data=data,
                extracted=extracted,
                from_voice=from_voice,
            )

    async def _handle_idle_step(
        self,
        transport: DialogTransport,
        user: User,
        text: str,
        data: DialogSessionData,
        *,
        from_voice: bool,
    ) -> None:
        if not await self._try_capture_problem_text(transport, user.id, data, text, retry_step=None):
            return
        user_phone = None if from_voice else user.phone
        missing_step = next_missing_step(data, user_phone)

        if missing_step == DialogStep.AWAITING_JK:
            await self._save_snapshot(user.id, DialogStep.AWAITING_JK, data)
            await transport.send_text("Приняла обращение. Оформим заявку: сначала выберите, пожалуйста, ЖК.", None)
            await transport.send_text(
                "Выберите, пожалуйста, ЖК:",
                build_jk_keyboard(self._services.housing_complexes, page=0),
            )
            return

        if missing_step == DialogStep.AWAITING_HOUSE:
            await self._save_snapshot(user.id, DialogStep.AWAITING_HOUSE, data)
            await transport.send_text("Приняла обращение. Уточните, пожалуйста, дом.", None)
            return

        if missing_step == DialogStep.AWAITING_ENTRANCE:
            await self._save_snapshot(user.id, DialogStep.AWAITING_ENTRANCE, data)
            await transport.send_text("Уточните подъезд. Если не знаете, напишите «-».", None)
            return

        if missing_step == DialogStep.AWAITING_APARTMENT:
            await self._save_snapshot(user.id, DialogStep.AWAITING_APARTMENT, data)
            await transport.send_text("Уточните номер квартиры.", None)
            return

        if missing_step == DialogStep.AWAITING_PHONE:
            await self._save_snapshot(user.id, DialogStep.AWAITING_PHONE, data)
            await transport.send_text("Укажите телефон для связи (например, +7XXXXXXXXXX).", None)
            return

        if missing_step == DialogStep.AWAITING_PROBLEM:
            await self._save_snapshot(user.id, DialogStep.AWAITING_PROBLEM, data)
            await transport.send_text("Опишите, пожалуйста, проблему в 1-2 предложениях.", None)
            return

        if missing_step == DialogStep.AWAITING_PHONE_REUSE_CONFIRM:
            await self._send_saved_phone_prompt(transport, user.id, data, user_phone)
            return

        await transport.send_text(collected_fields_text(data, user_phone), None)
        await self._classify_and_send_report_confirmation(transport, user.id, data)

    async def _handle_awaiting_jk(
        self,
        *,
        transport: DialogTransport,
        user: User,
        text: str,
        data: DialogSessionData,
        extracted: ExtractedReportContext,
        from_voice: bool,
    ) -> None:
        if extracted.jk:
            data.jk = extracted.jk
            if from_voice and not str(data.problem_text or "").strip():
                data.problem_text = text

            user_phone = None if from_voice else user.phone
            missing_step = next_missing_step(data, user_phone)
            if missing_step == DialogStep.AWAITING_REPORT_CONFIRM:
                await transport.send_text(collected_fields_text(data, user_phone), None)
                await self._classify_and_send_report_confirmation(transport, user.id, data)
                return
            if missing_step == DialogStep.AWAITING_PHONE_REUSE_CONFIRM:
                await self._send_saved_phone_prompt(transport, user.id, data, user_phone)
                return

            await self._save_snapshot(user.id, missing_step, data)
            if missing_step == DialogStep.AWAITING_HOUSE:
                await transport.send_text(f"ЖК зафиксировала: {extracted.jk}. Уточните, пожалуйста, дом.", None)
            elif missing_step == DialogStep.AWAITING_ENTRANCE:
                await transport.send_text(
                    f"ЖК зафиксировала: {extracted.jk}. Уточните подъезд. Если не знаете, напишите «-».",
                    None,
                )
            elif missing_step == DialogStep.AWAITING_APARTMENT:
                await transport.send_text(f"ЖК зафиксировала: {extracted.jk}. Уточните номер квартиры.", None)
            elif missing_step == DialogStep.AWAITING_PHONE:
                await transport.send_text(
                    f"ЖК зафиксировала: {extracted.jk}. Укажите телефон для связи (например, +7XXXXXXXXXX).",
                    None,
                )
            else:
                await transport.send_text(
                    f"ЖК зафиксировала: {extracted.jk}. Опишите, пожалуйста, проблему в 1-2 предложениях.",
                    None,
                )
            return

        reminder = "Выберите, пожалуйста, ЖК кнопками ниже."
        if self._services.speech.enabled:
            reminder += "\nГолосовые тоже поддерживаются: можете надиктовать проблему, а я уточню шаги."
        await transport.send_text(reminder, build_jk_keyboard(self._services.housing_complexes, 0))

    async def _handle_awaiting_house(
        self,
        *,
        transport: DialogTransport,
        user: User,
        text: str,
        data: DialogSessionData,
        extracted: ExtractedReportContext,
        from_voice: bool,
    ) -> None:
        _ = user, from_voice
        data.house = extracted.house if extracted.house else text
        await self._save_snapshot(user.id, DialogStep.AWAITING_ENTRANCE, data)
        await transport.send_text("Укажите подъезд. Если не знаете, напишите «-».", None)

    async def _handle_awaiting_entrance(
        self,
        *,
        transport: DialogTransport,
        user: User,
        text: str,
        data: DialogSessionData,
        extracted: ExtractedReportContext,
        from_voice: bool,
    ) -> None:
        _ = from_voice
        entrance_input = extracted.entrance if extracted.entrance else text
        data.entrance = cleanup_optional_field(entrance_input)
        await self._save_snapshot(user.id, DialogStep.AWAITING_APARTMENT, data)
        await transport.send_text("Укажите номер квартиры.", None)

    async def _handle_awaiting_apartment(
        self,
        *,
        transport: DialogTransport,
        user: User,
        text: str,
        data: DialogSessionData,
        extracted: ExtractedReportContext,
        from_voice: bool,
    ) -> None:
        data.apartment = extracted.apartment if extracted.apartment else text
        if str(data.problem_text or "").strip():
            await self._continue_after_problem_capture(transport, user, data, from_voice=from_voice)
            return

        if user.phone and not from_voice:
            await self._save_snapshot(user.id, DialogStep.AWAITING_PROBLEM, data)
            await transport.send_text("Опишите, пожалуйста, проблему в 1-2 предложениях.", None)
            return

        await self._save_snapshot(user.id, DialogStep.AWAITING_PHONE, data)
        await transport.send_text("Укажите телефон для связи (например, +7XXXXXXXXXX).", None)

    async def _handle_awaiting_phone(
        self,
        *,
        transport: DialogTransport,
        user: User,
        text: str,
        data: DialogSessionData,
        extracted: ExtractedReportContext,
        from_voice: bool,
    ) -> None:
        _ = from_voice
        phone = extracted.phone or normalize_phone(text)
        if phone is None:
            await transport.send_text(
                "Не удалось распознать номер. Напишите, пожалуйста, в формате +7XXXXXXXXXX.",
                None,
            )
            return

        data.phone = phone
        await self._services.storage.update_user_phone(user.id, phone)
        user.phone = phone
        if str(data.problem_text or "").strip():
            await self._continue_after_problem_capture(transport, user, data, from_voice=from_voice)
            return

        await self._save_snapshot(user.id, DialogStep.AWAITING_PROBLEM, data)
        await transport.send_text("Спасибо. Теперь коротко опишите проблему.", None)

    async def _handle_awaiting_problem(
        self,
        *,
        transport: DialogTransport,
        user: User,
        text: str,
        data: DialogSessionData,
        extracted: ExtractedReportContext,
        from_voice: bool,
    ) -> None:
        _ = extracted
        if not await self._try_capture_problem_text(
            transport,
            user.id,
            data,
            text,
            retry_step=DialogStep.AWAITING_PROBLEM,
        ):
            return
        await self._continue_after_problem_capture(transport, user, data, from_voice=from_voice)

    async def _handle_awaiting_phone_reuse_confirm(
        self,
        *,
        transport: DialogTransport,
        user: User,
        text: str,
        data: DialogSessionData,
        extracted: ExtractedReportContext,
        from_voice: bool,
    ) -> None:
        _ = from_voice
        phone = extracted.phone or normalize_phone(text)
        if phone is not None:
            data.phone = phone
            await self._services.storage.update_user_phone(user.id, phone)
            user.phone = phone
            await self._continue_after_problem_capture(transport, user, data, from_voice=from_voice)
            return

        if is_saved_phone_accept_text(text):
            if not user.phone:
                await self._save_snapshot(user.id, DialogStep.AWAITING_PHONE, data)
                await transport.send_text(
                    "Не нашла сохраненный номер. Укажите телефон для связи в формате +7XXXXXXXXXX.",
                    None,
                )
                return
            data.phone = user.phone
            await self._continue_after_problem_capture(transport, user, data, from_voice=from_voice)
            return

        if is_saved_phone_reject_text(text):
            await self._save_snapshot(user.id, DialogStep.AWAITING_PHONE, data)
            await transport.send_text("Укажите телефон для связи (например, +7XXXXXXXXXX).", None)
            return

        await transport.send_text(
            self._build_saved_phone_prompt(user.phone),
            build_phone_reuse_keyboard(str(user.phone or "")),
        )

    async def _handle_awaiting_category_confirm(
        self,
        *,
        transport: DialogTransport,
        user: User,
        text: str,
        data: DialogSessionData,
        extracted: ExtractedReportContext,
        from_voice: bool,
    ) -> None:
        _ = extracted, from_voice
        if is_yes_text(text):
            data.category = str(data.auto_category or "other")
            await self._send_report_confirmation(transport, user.id, data)
            return

        if is_no_or_other_text(text):
            await self._save_snapshot(user.id, DialogStep.AWAITING_CATEGORY_SELECT, data)
            await transport.send_text("Выберите подходящую категорию:", build_category_select_keyboard())
            return

        await transport.send_text(
            "Подтвердите категорию: нажмите кнопку или напишите «да» / «другое».",
            None,
        )

    async def _handle_awaiting_category_select(
        self,
        *,
        transport: DialogTransport,
        user: User,
        text: str,
        data: DialogSessionData,
        extracted: ExtractedReportContext,
        from_voice: bool,
    ) -> None:
        _ = extracted, from_voice
        parsed_category = category_from_text(
            text,
            categories=self._services.classifier.categories(),
            label_resolver=self._services.classifier.label,
        )
        if parsed_category is None:
            await transport.send_text("Выберите категорию кнопками ниже.", build_category_select_keyboard())
            return

        data.category = parsed_category
        await self._send_report_confirmation(transport, user.id, data)

    async def _handle_awaiting_report_confirm(
        self,
        *,
        transport: DialogTransport,
        user: User,
        text: str,
        data: DialogSessionData,
        extracted: ExtractedReportContext,
        from_voice: bool,
    ) -> None:
        _ = extracted, from_voice
        if is_yes_text(text):
            await self._save_snapshot(user.id, DialogStep.IDLE, DialogSessionData())
            await self._finalize_report(transport, user, data)
            return

        if is_no_or_other_text(text):
            await self._save_snapshot(user.id, DialogStep.AWAITING_REPORT_CORRECTION, data)
            await transport.send_text(
                "Напишите, что нужно исправить. Можно одним сообщением: адрес, телефон, описание проблемы или категорию. Потом я еще раз покажу сводку.",
                None,
            )
            return

        await transport.send_text(
            "Проверьте, пожалуйста, сводку и ответьте «да», если все верно, или «нет», если нужно исправить.",
            build_report_confirm_keyboard(),
        )

    async def _handle_awaiting_report_correction(
        self,
        *,
        transport: DialogTransport,
        user: User,
        text: str,
        data: DialogSessionData,
        extracted: ExtractedReportContext,
        from_voice: bool,
    ) -> None:
        _ = from_voice
        updated = data.model_copy(deep=True)
        if extracted.jk:
            updated.jk = extracted.jk
        if extracted.house:
            updated.house = extracted.house
        if extracted.entrance:
            updated.entrance = extracted.entrance
        if extracted.apartment:
            updated.apartment = extracted.apartment
        if extracted.phone:
            updated.phone = extracted.phone

        parsed_category = category_from_text(
            text,
            categories=self._services.classifier.categories(),
            label_resolver=self._services.classifier.label,
        )
        if parsed_category is not None:
            updated.category = parsed_category
            updated.auto_category = parsed_category

        if extracted.phone:
            await self._services.storage.update_user_phone(user.id, extracted.phone)

        correction_field = self._correction_field_from_text(text)
        if correction_field == "category":
            await self._save_snapshot(user.id, DialogStep.AWAITING_CATEGORY_SELECT, updated)
            await transport.send_text(
                "Выберите категорию кнопками ниже или напишите ее текстом.",
                build_category_select_keyboard(),
            )
            return
        if correction_field == "address":
            await transport.send_text(
                "Напишите адрес одним сообщением: дом, подъезд и квартира. ЖК можно тоже указать, если нужно.",
                None,
            )
            return
        if correction_field == "phone":
            await transport.send_text("Напишите новый телефон в формате +7XXXXXXXXXX.", None)
            return
        if correction_field == "problem":
            await transport.send_text("Напишите новое описание проблемы в 1-2 предложениях.", None)
            return

        no_structured_updates = (
            extracted.jk is None
            and extracted.house is None
            and extracted.entrance is None
            and extracted.apartment is None
            and extracted.phone is None
            and parsed_category is None
        )
        if no_structured_updates and text.strip():
            if not await self._try_capture_problem_text(
                transport,
                user.id,
                updated,
                text,
                retry_step=DialogStep.AWAITING_REPORT_CORRECTION,
            ):
                return

        await self._send_report_confirmation(transport, user.id, updated)

    async def _reset_to_new_request(self, transport: DialogTransport, user_id: int) -> None:
        await self._save_snapshot(user_id, DialogStep.AWAITING_JK, DialogSessionData())
        await transport.send_text(
            "Готова помочь с новой заявкой. Выберите, пожалуйста, ЖК:",
            build_jk_keyboard(self._services.housing_complexes, 0),
        )

    async def _send_onboarding(self, transport: DialogTransport, *, include_welcome: bool) -> None:
        text = (
            WELCOME_TEXT
            if include_welcome
            else (
                "Через меня можно быстро отправить заявку в диспетчерскую — текстом или голосом.\n\n"
                "Сначала выберите ваш жилой комплекс:"
            )
        )
        await transport.send_text(text, build_jk_keyboard(self._services.housing_complexes, page=0))

    async def _ask_category_confirmation(
        self,
        transport: DialogTransport,
        user_id: int,
        data: DialogSessionData,
    ) -> None:
        result = await self._classify_problem(str(data.problem_text or ""))
        data.auto_category = result.category
        await self._save_snapshot(user_id, DialogStep.AWAITING_CATEGORY_CONFIRM, data)

        label = self._services.classifier.label(result.category)
        await transport.send_text(
            (
                f"Похоже, это категория заявки: «{label}». Подтвердите, пожалуйста. "
                "Если не уверены, нажмите «Выбрать другую»."
            ),
            build_category_confirm_keyboard(),
        )

    async def _classify_and_send_report_confirmation(
        self,
        transport: DialogTransport,
        user_id: int,
        data: DialogSessionData,
    ) -> None:
        result = await self._classify_problem(str(data.problem_text or ""))
        data.auto_category = result.category
        data.category = data.category or result.category
        await self._send_report_confirmation(transport, user_id, data)

    async def _continue_after_problem_capture(
        self,
        transport: DialogTransport,
        user: User,
        data: DialogSessionData,
        *,
        from_voice: bool,
    ) -> None:
        validation = validate_problem_text(str(data.problem_text or ""))
        if not validation.is_valid:
            await self._save_snapshot(user.id, DialogStep.AWAITING_PROBLEM, data)
            await transport.send_text(problem_text_rejection_message(validation), None)
            return

        if not str(data.phone or "").strip():
            saved_phone = None if from_voice else str(user.phone or "").strip()
            if saved_phone:
                await self._send_saved_phone_prompt(transport, user.id, data, saved_phone)
                return
            await self._save_snapshot(user.id, DialogStep.AWAITING_PHONE, data)
            await transport.send_text("Укажите телефон для связи (например, +7XXXXXXXXXX).", None)
            return

        await self._classify_and_send_report_confirmation(transport, user.id, data)

    async def _send_saved_phone_prompt(
        self,
        transport: DialogTransport,
        user_id: int,
        data: DialogSessionData,
        phone: str | None,
    ) -> None:
        saved_phone = str(phone or "").strip()
        if not saved_phone:
            await self._save_snapshot(user_id, DialogStep.AWAITING_PHONE, data)
            await transport.send_text("Укажите телефон для связи (например, +7XXXXXXXXXX).", None)
            return

        await self._save_snapshot(user_id, DialogStep.AWAITING_PHONE_REUSE_CONFIRM, data)
        await transport.send_text(
            self._build_saved_phone_prompt(saved_phone),
            build_phone_reuse_keyboard(saved_phone),
        )

    async def _handle_report_status_request(
        self,
        transport: DialogTransport,
        user: User,
        snapshot: DialogSnapshot,
    ) -> None:
        report = await self._report_lookup_service.get_latest_relevant_report(user.id)
        reply = self._report_lookup_service.build_reply(report)

        if False and report is None:
            reply = "Ранее зарегистрированных заявок не нашла."
        else:
            reply = reply

        resume_prompt = build_resume_prompt(snapshot.step)
        if resume_prompt:
            reply = f"{reply}\n\n{resume_prompt}"

        await transport.send_text(reply, None)

    async def _send_report_confirmation(
        self,
        transport: DialogTransport,
        user_id: int,
        data: DialogSessionData,
    ) -> None:
        await self._save_snapshot(user_id, DialogStep.AWAITING_REPORT_CONFIRM, data)
        await transport.send_text(
            self._build_report_review(data),
            build_report_confirm_keyboard(),
        )

    async def _classify_problem(self, problem_text: str) -> ClassificationResult:
        return await self._category_service.classify(problem_text)

    async def _finalize_report(
        self,
        transport: DialogTransport,
        user: User,
        data: DialogSessionData,
    ) -> None:
        result = await self._report_finalizer.finalize_report(user=user, data=data)
        await transport.send_text(result.reply_text, None)
        if self._services.bitrix_service.enabled:
            self._runtime.register_background_task(
                self._report_finalizer.sync_bitrix_ticket(
                    report=result.report,
                    user=user,
                    is_mass_incident=result.is_mass_incident,
                )
            )
        return

        draft = self._build_finalized_report_draft(data, user)
        report = await self._services.storage.create_report(
            ReportCreate(
                user_id=user.id,
                jk=draft.jk,
                address=draft.address,
                apt=draft.apartment,
                phone=draft.phone,
                category=draft.category,
                text=draft.problem_text,
                scope_key=draft.scope_key,
            )
        )

        incident = await self._services.incidents.evaluate_report(report)
        normalized_report = {
            "local_report_id": report.id,
            "user_id": user.id,
            "telegram_id": user.telegram_id,
            "jk": draft.jk,
            "address": draft.address,
            "apartment": draft.apartment,
            "phone": draft.phone,
            "category": draft.category,
            "scope_key": draft.scope_key,
            "problem_text": draft.problem_text,
        }
        composition_payload = build_report_composition_payload(
            source_session=data.to_mapping(),
            normalized_report=normalized_report,
            category_label=self._services.classifier.label(draft.category),
            is_mass_incident=incident.is_mass,
            incident_id=incident.incident_id,
        )
        await self._store_audit_log(
            report_id=report.id,
            stage=ReportAuditStage.REPORT_CREATED.value,
            payload=composition_payload,
        )

        standard_reply = await self._services.responder.report_created(local_id=report.id, bitrix_id=None)
        summary = self._build_report_summary(
            report_id=report.id,
            category=draft.category,
            jk=draft.jk,
            house=draft.house,
            entrance=draft.entrance,
            apartment=draft.apartment,
        )

        chunks = [standard_reply]
        if incident.is_mass and incident.public_message:
            chunks.append(incident.public_message)
            chunks.append(f"Номер заявки: {report.id}.")
        chunks.append(summary)
        reply = "\n\n".join(chunk for chunk in chunks if chunk)

        if draft.jk is None:
            reply += "\n\nЕсли сможете, дополнительно напишите ЖК — я добавлю в заявку."

        await transport.send_text(reply, None)

        if self._services.bitrix_service.enabled:
            self._runtime.register_background_task(
                self._sync_bitrix_ticket(
                    report=report,
                    user=user,
                    is_mass_incident=incident.is_mass,
                )
            )

    async def _sync_bitrix_ticket(
        self,
        *,
        report: Report,
        user: User,
        is_mass_incident: bool,
    ) -> None:
        await self._report_finalizer.sync_bitrix_ticket(
            report=report,
            user=user,
            is_mass_incident=is_mass_incident,
        )
        return

        try:
            bitrix_id = await self._services.bitrix_service.create_ticket(report=report, user=user)
            await self._services.storage.set_report_bitrix_id(report.id, bitrix_id)
        except BitrixClientError as error:
            await self._store_audit_log(
                report_id=report.id,
                stage=ReportAuditStage.BITRIX_SYNC_FAILED.value,
                payload=build_bitrix_audit_payload(
                    bitrix_id=None,
                    status=BitrixSyncStatus.FAILED.value,
                    error=str(error),
                ),
            )
            logger.warning("Bitrix ticket creation failed for report %s: %s", report.id, error)
            await self._services.notifier.send_message(
                telegram_id=user.telegram_id,
                text=(
                    f"Заявка №{report.id} уже сохранена. "
                    "Передачу в Bitrix24 уточняю вручную и вернусь с обновлением."
                ),
            )
            return

        await self._store_audit_log(
            report_id=report.id,
            stage=ReportAuditStage.BITRIX_SYNCED.value,
            payload=build_bitrix_audit_payload(
                bitrix_id=bitrix_id,
                status=BitrixSyncStatus.SYNCED.value,
            ),
        )

        if is_mass_incident:
            followup = f"Дополнительно: заявка №{report.id} передана в Bitrix24, номер {bitrix_id}."
        else:
            followup = f"Заявка №{report.id} передана в Bitrix24. Номер в Bitrix24: {bitrix_id}."
        await self._services.notifier.send_message(telegram_id=user.telegram_id, text=followup)

    def _build_finalized_report_draft(self, data: DialogSessionData, user: User) -> FinalizedReportDraft:
        jk_value = str(data.jk or "").strip()
        jk = jk_value if jk_value and jk_value != UNKNOWN_JK_VALUE else None

        house = str(data.house or "").strip()
        entrance = cleanup_optional_field(str(data.entrance or ""))
        apartment = str(data.apartment or "").strip()
        phone = str(data.phone or "").strip()
        problem_text = str(data.problem_text or "").strip()
        category = str(data.category or data.auto_category or "other")

        return FinalizedReportDraft(
            jk=jk,
            house=house,
            entrance=entrance,
            apartment=apartment,
            phone=phone,
            problem_text=problem_text,
            category=category,
            address=build_address(house=house, entrance=entrance, apartment=apartment),
            scope_key=compose_scope_key(jk=jk, category=category),
        )

    def _build_report_summary(
        self,
        *,
        report_id: int,
        category: str,
        jk: str | None,
        house: str,
        entrance: str | None,
        apartment: str,
    ) -> str:
        lines = [
            "Сводка по заявке:",
            f"Тип: {self._services.classifier.label(category)}",
            f"ЖК: {jk or 'не указан'}",
            f"Дом: {house}",
            f"Подъезд: {entrance or 'не указан'}",
            f"Квартира: {apartment}",
            f"Статус: создана (локальный №{report_id})",
        ]
        if self._services.bitrix_service.enabled:
            lines.append("Bitrix24: передаю заявку, номер пришлю отдельным сообщением.")
        else:
            lines.append("Bitrix24: интеграция сейчас выключена.")
        return "\n".join(lines)

    def _build_report_review(self, data: DialogSessionData) -> str:
        category = str(data.category or data.auto_category or "other")
        return build_report_review(
            ReportReviewView(
                category_label=self._services.classifier.label(category),
                jk=data.jk,
                house=data.house,
                entrance=data.entrance,
                apartment=data.apartment,
                phone=data.phone,
                problem_text=data.problem_text,
            )
        )

        category = str(data.category or data.auto_category or "other")
        return "\n".join(
            [
                "Проверьте, пожалуйста, заявку перед отправкой:",
                f"Тип: {self._services.classifier.label(category)}",
                f"ЖК: {data.jk or 'не указан'}",
                f"Дом: {data.house or 'не указан'}",
                f"Подъезд: {data.entrance or 'не указан'}",
                f"Квартира: {data.apartment or 'не указана'}",
                f"Телефон: {data.phone or 'не указан'}",
                f"Проблема: {data.problem_text or 'не указана'}",
                "",
                "Если все верно, подтвердите заявку. Если нет, выберите исправление.",
                "Можно исправить адрес, телефон, описание проблемы или категорию одним сообщением.",
            ]
        )

    def _build_saved_phone_prompt(self, phone: str | None) -> str:
        return build_saved_phone_prompt(phone)

        saved_phone = str(phone or "").strip()
        if not saved_phone:
            return "Не нашла сохраненный номер. Укажите телефон для связи в формате +7XXXXXXXXXX."
        return (
            f"Для связи у меня сохранен номер {saved_phone}.\n"
            "Использовать его для этой заявки или указать другой?"
        )

    def _build_report_lookup_reply(self, report: ReportLookupResult) -> str:
        created_at = report.created_at.astimezone().strftime("%d.%m.%Y %H:%M")
        lines = [
            "Нашла последнюю заявку:",
            f"Номер: {report.report_id}",
            f"Статус: {report.status or 'не указан'}",
            f"Создана: {created_at}",
            f"Тип: {self._services.classifier.label(report.category)}",
            f"Адрес: {report.address}",
        ]
        if report.jk:
            lines.append(f"ЖК: {report.jk}")
        if report.bitrix_id:
            lines.append(f"Bitrix24: {report.bitrix_id}")
        return "\n".join(lines)

    def _build_resume_prompt(self, step: DialogStep) -> str | None:
        return build_resume_prompt(step)

        prompts = {
            DialogStep.AWAITING_JK: "Черновик новой заявки сохранила. Чтобы продолжить, выберите ЖК.",
            DialogStep.AWAITING_HOUSE: "Черновик новой заявки сохранила. Чтобы продолжить, напишите дом.",
            DialogStep.AWAITING_ENTRANCE: "Черновик новой заявки сохранила. Чтобы продолжить, укажите подъезд.",
            DialogStep.AWAITING_APARTMENT: "Черновик новой заявки сохранила. Чтобы продолжить, укажите квартиру.",
            DialogStep.AWAITING_PHONE: "Черновик новой заявки сохранила. Чтобы продолжить, отправьте телефон.",
            DialogStep.AWAITING_PROBLEM: "Черновик новой заявки сохранила. Чтобы продолжить, опишите проблему.",
            DialogStep.AWAITING_PHONE_REUSE_CONFIRM: (
                "Черновик новой заявки сохранила. Чтобы продолжить, подтвердите сохраненный номер или отправьте новый."
            ),
            DialogStep.AWAITING_REPORT_CONFIRM: (
                "Черновик новой заявки сохранила. Чтобы продолжить, подтвердите сводку или выберите исправление."
            ),
            DialogStep.AWAITING_REPORT_CORRECTION: (
                "Черновик новой заявки сохранила. Чтобы продолжить, напишите, что нужно исправить."
            ),
        }
        return prompts.get(step)

    def _correction_field_from_text(self, text: str) -> str | None:
        value = normalize_text(text)
        if value in {"категория", "категорию", "тип", "тип заявки"}:
            return "category"
        if value in {"адрес", "дом", "подъезд", "квартира"}:
            return "address"
        if value in {"телефон", "номер", "номер телефона"}:
            return "phone"
        if value in {"описание", "описание проблемы", "проблему", "текст"}:
            return "problem"
        return None

    async def _try_capture_problem_text(
        self,
        transport: DialogTransport,
        user_id: int,
        data: DialogSessionData,
        text: str,
        *,
        retry_step: DialogStep | None,
    ) -> bool:
        validation = validate_problem_text(text)
        if validation.is_valid:
            data.problem_text = text.strip()
            return True

        if retry_step is not None:
            await self._save_snapshot(user_id, retry_step, data)
        await transport.send_text(problem_text_rejection_message(validation), None)
        return False

    async def _sync_extracted_phone(self, user: User, extracted: ExtractedReportContext) -> None:
        if extracted.phone and extracted.phone != user.phone:
            await self._services.storage.update_user_phone(user.id, extracted.phone)

    async def _upsert_user(self, telegram_id: int, display_name: str | None) -> User:
        return await self._services.storage.upsert_user(telegram_id=telegram_id, name=display_name)

    async def _load_snapshot(self, user_id: int) -> DialogSnapshot:
        payload = await self._services.storage.get_session(user_id)
        return DialogSnapshot(
            step=dialog_step(payload.step),
            data=DialogSessionData.from_mapping(payload.data),
        )

    async def _save_snapshot(self, user_id: int, step: DialogStep, data: DialogSessionData) -> None:
        await self._services.storage.save_session(
            user_id=user_id,
            payload=SessionPayload(step=step.value, data=data.to_mapping()),
        )

    async def _store_audit_log(
        self,
        *,
        report_id: int,
        stage: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            await self._services.storage.create_report_audit(
                ReportAuditCreate(
                    report_id=report_id,
                    stage=stage,
                    regulation_version=REGULATION_VERSION,
                    payload=payload,
                )
            )
        except Exception as error:
            logger.warning("Report audit log save failed for report %s at stage %s: %s", report_id, stage, error)
