from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.buildings import BuildingRegistry, HouseInfo
from app.core.models import User
from app.core.schemas import SessionPayload
from app.core.services import DialogDeps
from app.core.utils import normalize_phone
from app.telegram.constants import CATEGORY_LABELS, UNKNOWN_JK_VALUE, WELCOME_TEXT
from app.telegram.dialog.classification import DialogCategoryService
from app.telegram.dialog.correction_flow import DialogCorrectionFlow
from app.telegram.dialog.finalization import DialogReportFinalizer, ReportLimitExceeded
from app.telegram.dialog.formatters import (
    ReportReviewView,
    build_category_options_hint,
    build_report_review,
    build_resume_prompt,
    build_saved_phone_prompt,
)
from app.telegram.dialog.idle_flow import resolve_idle_flow
from app.telegram.dialog.models import ClassificationResult, DialogSessionData, DialogSnapshot, DialogStep, DialogTransport
from app.telegram.dialog.preprocessing import DialogInputPreprocessor
from app.telegram.dialog.problem_validation import problem_text_rejection_message, validate_problem_text
from app.telegram.dialog.state_machine import (
    category_from_text,
    cleanup_optional_field,
    collected_fields_text,
    dialog_step,
    is_no_or_other_text,
    is_saved_phone_accept_text,
    is_saved_phone_reject_text,
    is_yes_text,
)
from app.telegram.dialog.keyboard_protocol import KeyboardFactory
from app.telegram.dialog.status_service import DialogReportLookupService
from app.telegram.extractors import ExtractedReportContext
from app.telegram.phrases import is_farewell_or_thanks, is_greeting

if TYPE_CHECKING:
    from app.core.services import AppServices


_STALE_CALLBACK_TEXT = "Эта кнопка уже неактуальна. Напишите сообщение, и я продолжу оформление заявки."
_PHONE_PROMPT_TEXT = "Укажите телефон для связи (например, +7XXXXXXXXXX)."
_PROBLEM_PROMPT_TEXT = "Опишите, пожалуйста, проблему в 1-2 предложениях."
_REPORT_CORRECTION_PROMPT = (
    "Напишите, что нужно исправить. Можно одним сообщением: адрес, телефон, описание проблемы "
    "или категорию. Потом я еще раз покажу сводку."
)

STANDALONE_JK_MARKER = "__standalone__"


class DialogService:
    def __init__(self, services: AppServices, *, keyboard_factory: KeyboardFactory | None = None):
        self._deps: DialogDeps = services.dialog_deps()
        self._registry: BuildingRegistry = self._deps.building_registry
        self._runtime = self._deps.dialog_runtime
        if keyboard_factory is None:
            from app.telegram.keyboards import TelegramKeyboardFactory
            keyboard_factory = TelegramKeyboardFactory()
        self._kb: KeyboardFactory = keyboard_factory
        self._preprocessor = DialogInputPreprocessor(
            storage=self._deps.storage,
            housing_complexes=self._registry.complex_names,
        )
        self._category_service = DialogCategoryService(self._deps.classifier)
        self._report_lookup_service = DialogReportLookupService(
            self._deps.storage,
            self._deps.classifier.label,
            bitrix_service=self._deps.bitrix_service,
        )
        self._report_finalizer = DialogReportFinalizer(
            storage=self._deps.storage,
            incidents=self._deps.incidents,
            responder=self._deps.responder,
            bitrix_service=self._deps.bitrix_service,
            notifier=self._deps.notifier,
            label_resolver=self._deps.classifier.label,
            building_registry=self._registry,
            confirmation_budget_ms=services.settings.report_confirmation_budget_ms,
        )
        self._correction_flow = DialogCorrectionFlow(
            categories=self._deps.classifier.categories(),
            label_resolver=self._deps.classifier.label,
        )

    # ── Public entry points ──

    async def start(self, transport: DialogTransport, *, include_welcome: bool) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step not in (DialogStep.IDLE, DialogStep.AWAITING_JK):
                await self._save_snapshot(user.id, DialogStep.AWAITING_JK, DialogSessionData())
                await transport.send_text(
                    "Предыдущая заявка сброшена. Начнём новую — выберите ЖК:",
                    self._kb.jk_keyboard(self._registry.complex_names, page=0),
                )
                return
            await self._save_snapshot(user.id, DialogStep.AWAITING_JK, DialogSessionData())
            await self._send_onboarding(transport, include_welcome=include_welcome)

    async def select_housing_complex(self, transport: DialogTransport, complex_name: str) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_JK:
                await transport.send_text(_STALE_CALLBACK_TEXT, None)
                return
            data = snapshot.data.model_copy()
            data.jk = complex_name

            houses = self._registry.houses_for_complex(complex_name)
            if len(houses) == 1:
                house = houses[0]
                data.house = house.address
                if house.entrances == 1:
                    data.entrance = "1"
                    await self._save_snapshot(user.id, DialogStep.AWAITING_APARTMENT, data)
                    await transport.send_text(
                        f"ЖК: {complex_name}, {house.address}. Укажите номер квартиры.",
                        None,
                    )
                else:
                    await self._save_snapshot(user.id, DialogStep.AWAITING_ENTRANCE, data)
                    await transport.send_text(
                        f"ЖК: {complex_name}, {house.address}. Выберите подъезд:",
                        self._kb.entrance_keyboard(house.entrances),
                    )
            elif len(houses) > 1:
                await self._save_snapshot(user.id, DialogStep.AWAITING_HOUSE, data)
                await transport.send_text(
                    f"ЖК: {complex_name}. Выберите дом:",
                    self._kb.house_keyboard(houses, page=0),
                )
            else:
                await self._save_snapshot(user.id, DialogStep.AWAITING_HOUSE, data)
                await transport.send_text("Спасибо. Уточните, пожалуйста, дом.", None)

    async def show_standalone_houses(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_JK:
                await transport.send_text(_STALE_CALLBACK_TEXT, None)
                return
            data = snapshot.data.model_copy()
            data.jk = STANDALONE_JK_MARKER
            houses = self._registry.standalone_houses
            if not houses:
                data.jk = UNKNOWN_JK_VALUE
                await self._save_snapshot(user.id, DialogStep.AWAITING_HOUSE, data)
                await transport.send_text("Подскажите адрес: дом, подъезд и квартиру. Сначала — дом.", None)
                return
            await self._save_snapshot(user.id, DialogStep.AWAITING_HOUSE, data)
            await transport.send_text(
                "Выберите ваш дом:",
                self._kb.house_keyboard(houses, page=0),
            )

    async def paginate_houses(self, transport: DialogTransport, page: int) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_HOUSE:
                return
            houses = self._get_current_house_list(snapshot.data)
            await transport.clear_inline_keyboard()
            await transport.send_text("Выберите дом:", self._kb.house_keyboard(houses, page=page))

    async def select_house(self, transport: DialogTransport, index: int) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_HOUSE:
                await transport.send_text(_STALE_CALLBACK_TEXT, None)
                return
            data = snapshot.data.model_copy()
            houses = self._get_current_house_list(data)
            if index < 0 or index >= len(houses):
                await transport.send_text("Дом не найден. Выберите из списка.", self._kb.house_keyboard(houses, 0))
                return
            house = houses[index]
            data.house = house.address

            if data.jk == STANDALONE_JK_MARKER:
                complex_name = self._registry.complex_for_house(house.address)
                data.jk = complex_name or UNKNOWN_JK_VALUE

            if house.entrances == 1:
                data.entrance = "1"
                await self._save_snapshot(user.id, DialogStep.AWAITING_APARTMENT, data)
                await transport.send_text(f"Дом: {house.address}. Укажите номер квартиры.", None)
            else:
                await self._save_snapshot(user.id, DialogStep.AWAITING_ENTRANCE, data)
                await transport.send_text(
                    f"Дом: {house.address}. Выберите подъезд:",
                    self._kb.entrance_keyboard(house.entrances),
                )

    async def select_entrance(self, transport: DialogTransport, entrance: str) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_ENTRANCE:
                await transport.send_text(_STALE_CALLBACK_TEXT, None)
                return
            data = snapshot.data.model_copy()
            house_info = self._registry.find_house(str(data.house or ""))
            if house_info and entrance.isdigit():
                n = int(entrance)
                if n < 1 or n > house_info.entrances:
                    await transport.send_text(
                        f"В этом доме {house_info.entrances} подъезд(ов). Выберите от 1 до {house_info.entrances}.",
                        self._kb.entrance_keyboard(house_info.entrances),
                    )
                    return
            data.entrance = entrance
            await self._save_snapshot(user.id, DialogStep.AWAITING_APARTMENT, data)
            await transport.send_text("Укажите номер квартиры.", None)

    async def mark_unknown_housing_complex(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_JK:
                await transport.send_text(_STALE_CALLBACK_TEXT, None)
                return
            data = snapshot.data.model_copy()
            data.jk = UNKNOWN_JK_VALUE
            await self._save_snapshot(user.id, DialogStep.AWAITING_HOUSE, data)
            await transport.send_text(
                "Поняла. Тогда подскажите адрес: дом, подъезд (если есть) и квартиру. Сначала — дом.",
                None,
            )

    async def confirm_category(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_CATEGORY_CONFIRM:
                await transport.send_text(_STALE_CALLBACK_TEXT, None)
                return

            data = snapshot.data.model_copy()
            data.category = str(data.auto_category or "other")
            await transport.clear_inline_keyboard()
            await self._send_report_confirmation(transport, user.id, data)

    async def request_manual_category(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_CATEGORY_CONFIRM:
                await transport.send_text(_STALE_CALLBACK_TEXT, None)
                return

            await self._save_snapshot(user.id, DialogStep.AWAITING_CATEGORY_SELECT, snapshot.data)
            await transport.clear_inline_keyboard()
            await transport.send_text("Выберите подходящую категорию:", self._kb.category_select_keyboard())

    async def select_category(self, transport: DialogTransport, category: str) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_CATEGORY_SELECT:
                await transport.send_text(_STALE_CALLBACK_TEXT, None)
                return

            if category not in CATEGORY_LABELS:
                await transport.send_text(
                    "Не удалось определить категорию. Напишите проблему еще раз, и я продолжу.",
                    None,
                )
                return

            data = snapshot.data.model_copy()
            data.category = category
            await transport.clear_inline_keyboard()
            await self._send_report_confirmation(transport, user.id, data)

    async def confirm_saved_phone(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_PHONE_REUSE_CONFIRM:
                await transport.send_text(_STALE_CALLBACK_TEXT, None)
                return

            await transport.clear_inline_keyboard()
            if not user.phone:
                await self._save_snapshot(user.id, DialogStep.AWAITING_PHONE, snapshot.data)
                await transport.send_text(
                    "Не нашла сохраненный номер. Укажите телефон для связи в формате +7XXXXXXXXXX.",
                    None,
                )
                return

            data = snapshot.data.model_copy()
            data.phone = user.phone
            await self._continue_after_problem_capture(transport, user, data, from_voice=False)

    async def request_new_phone(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_PHONE_REUSE_CONFIRM:
                await transport.send_text(_STALE_CALLBACK_TEXT, None)
                return

            await self._save_snapshot(user.id, DialogStep.AWAITING_PHONE, snapshot.data)
            await transport.clear_inline_keyboard()
            await transport.send_text(_PHONE_PROMPT_TEXT, None)

    async def confirm_report(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_REPORT_CONFIRM:
                await transport.send_text(_STALE_CALLBACK_TEXT, None)
                return

            await self._save_snapshot(user.id, DialogStep.IDLE, DialogSessionData())
            await transport.clear_inline_keyboard()
            await self._finalize_report(transport, user, snapshot.data)

    async def request_report_correction(self, transport: DialogTransport) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            if snapshot.step != DialogStep.AWAITING_REPORT_CONFIRM:
                await transport.send_text(_STALE_CALLBACK_TEXT, None)
                return

            await self._save_snapshot(user.id, DialogStep.AWAITING_REPORT_CORRECTION, snapshot.data)
            await transport.clear_inline_keyboard()
            await transport.send_text(self._build_report_correction_prompt(), None)

    async def process_text(self, transport: DialogTransport, text: str, *, from_voice: bool = False) -> None:
        user = await self._upsert_user(transport.platform_user_id, transport.display_name)
        async with self._runtime.user_lock(user.id):
            snapshot = await self._load_snapshot(user.id)
            preprocessed = await self._preprocessor.preprocess(user=user, snapshot=snapshot, text=text)
            if preprocessed.status_requested:
                await self._handle_report_status_request(transport, user, snapshot)
                return

            if snapshot.step == DialogStep.IDLE and is_farewell_or_thanks(preprocessed.text):
                await transport.send_text(
                    "Пожалуйста. Если понадобится помощь, просто напишите проблему — я сразу начну оформление заявки.",
                    None,
                )
                return

            if snapshot.step == DialogStep.IDLE and is_greeting(preprocessed.text):
                await self._save_snapshot(user.id, DialogStep.AWAITING_JK, DialogSessionData())
                await self._send_onboarding(transport, include_welcome=False)
                return

            if snapshot.step == DialogStep.IDLE:
                await self._handle_idle_step(
                    transport=transport,
                    user=user,
                    text=preprocessed.text,
                    data=preprocessed.data,
                    from_voice=from_voice,
                )
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
                and preprocessed.data.house
                and preprocessed.data.apartment
                and preprocessed.data.phone
            ):
                if not await self._try_capture_problem_text(
                    transport,
                    user.id,
                    preprocessed.data,
                    preprocessed.text,
                    retry_step=DialogStep.AWAITING_PROBLEM,
                ):
                    return
                await transport.send_text(collected_fields_text(preprocessed.data, None), None)
                await self._continue_after_problem_capture(
                    transport,
                    user,
                    preprocessed.data,
                    from_voice=True,
                )
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
                text=preprocessed.text,
                data=preprocessed.data,
                extracted=preprocessed.extracted,
                from_voice=from_voice,
            )

    # ── Internal step handlers ──

    async def _handle_idle_step(
        self,
        *,
        transport: DialogTransport,
        user: User,
        text: str,
        data: DialogSessionData,
        from_voice: bool,
    ) -> None:
        if not await self._try_capture_problem_text(transport, user.id, data, text, retry_step=None):
            return

        # Voice shortcut: if voice extracted JK, resolve house from registry
        # and skip inline-button steps for already-known fields.
        if from_voice and data.jk:
            self._resolve_voice_house(data)

        user_phone = None if from_voice else user.phone
        decision = resolve_idle_flow(
            data=data,
            user_phone=user_phone,
            housing_complexes=self._registry.complex_names,
            keyboard_factory=self._kb,
        )

        if decision.request_saved_phone_reuse:
            await self._send_saved_phone_prompt(transport, user.id, data, user_phone)
            return

        if decision.ready_for_confirmation:
            await transport.send_text(collected_fields_text(data, user_phone), None)
            await self._classify_and_send_report_confirmation(transport, user.id, data)
            return

        # For voice: if we end up needing JK buttons but JK was extracted, show collected info
        if from_voice and data.jk and decision.next_step != DialogStep.AWAITING_JK:
            prefix = f"Из голосового зафиксировала: ЖК {data.jk}."
            if data.house:
                prefix += f" Дом: {data.house}."
            prompt = decision.prompt_text or _PROBLEM_PROMPT_TEXT
            await self._save_snapshot(user.id, decision.next_step, data)
            await transport.send_text(f"{prefix}\n{prompt}", decision.reply_markup)
            return

        await self._save_snapshot(user.id, decision.next_step, data)
        await transport.send_text(decision.prompt_text or _PROBLEM_PROMPT_TEXT, decision.reply_markup)

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
        if not extracted.jk:
            reminder = "Выберите, пожалуйста, ЖК кнопками ниже."
            if self._deps.speech.enabled:
                reminder += "\nГолосовые тоже поддерживаются: можно надиктовать проблему, а я уточню шаги."
            await transport.send_text(reminder, self._kb.jk_keyboard(self._registry.complex_names, 0))
            return

        data.jk = extracted.jk
        if from_voice and not str(data.problem_text or "").strip():
            data.problem_text = text
        if from_voice:
            self._resolve_voice_house(data)

        user_phone = None if from_voice else user.phone
        decision = resolve_idle_flow(
            data=data,
            user_phone=user_phone,
            housing_complexes=self._registry.complex_names,
            keyboard_factory=self._kb,
        )
        if decision.request_saved_phone_reuse:
            await self._send_saved_phone_prompt(transport, user.id, data, user_phone)
            return
        if decision.ready_for_confirmation:
            await transport.send_text(collected_fields_text(data, user_phone), None)
            await self._classify_and_send_report_confirmation(transport, user.id, data)
            return

        await self._save_snapshot(user.id, decision.next_step, data)
        prefix = f"ЖК зафиксировала: {extracted.jk}. "
        await transport.send_text(prefix + (decision.prompt_text or _PROBLEM_PROMPT_TEXT), decision.reply_markup)

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
        _ = from_voice
        data.house = extracted.house if extracted.house else text
        house_info = self._registry.find_house(data.house)
        if house_info and house_info.entrances == 1:
            data.entrance = "1"
            await self._save_snapshot(user.id, DialogStep.AWAITING_APARTMENT, data)
            await transport.send_text("Укажите номер квартиры.", None)
        elif house_info and house_info.entrances > 1:
            await self._save_snapshot(user.id, DialogStep.AWAITING_ENTRANCE, data)
            await transport.send_text(
                "Выберите подъезд:",
                self._kb.entrance_keyboard(house_info.entrances),
            )
        else:
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
        cleaned = cleanup_optional_field(entrance_input)
        if cleaned is not None:
            house_info = self._registry.find_house(str(data.house or ""))
            if house_info and cleaned.isdigit():
                n = int(cleaned)
                if n < 1 or n > house_info.entrances:
                    await transport.send_text(
                        f"В этом доме {house_info.entrances} подъезд(ов). Укажите от 1 до {house_info.entrances}, или «-» если не знаете.",
                        self._kb.entrance_keyboard(house_info.entrances),
                    )
                    return
        data.entrance = cleaned
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
        apt_input = extracted.apartment if extracted.apartment else text
        house_info = self._registry.find_house(str(data.house or ""))
        if house_info and apt_input.strip().isdigit():
            n = int(apt_input.strip())
            if n < 1 or n > house_info.apartments:
                await transport.send_text(
                    f"В этом доме квартиры от 1 до {house_info.apartments}. Укажите корректный номер.",
                    None,
                )
                return
        data.apartment = apt_input
        if str(data.problem_text or "").strip():
            await self._continue_after_problem_capture(transport, user, data, from_voice=from_voice)
            return

        if user.phone and not from_voice:
            await self._save_snapshot(user.id, DialogStep.AWAITING_PROBLEM, data)
            await transport.send_text(_PROBLEM_PROMPT_TEXT, None)
            return

        await self._save_snapshot(user.id, DialogStep.AWAITING_PHONE, data)
        await transport.send_text(_PHONE_PROMPT_TEXT, None)

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
        await self._deps.storage.update_user_phone(user.id, phone)
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
            await self._deps.storage.update_user_phone(user.id, phone)
            user.phone = phone
            await self._continue_after_problem_capture(transport, user, data, from_voice=False)
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
            await self._continue_after_problem_capture(transport, user, data, from_voice=False)
            return

        if is_saved_phone_reject_text(text):
            await self._save_snapshot(user.id, DialogStep.AWAITING_PHONE, data)
            await transport.send_text(_PHONE_PROMPT_TEXT, None)
            return

        await transport.send_text(
            build_saved_phone_prompt(user.phone),
            self._kb.phone_reuse_keyboard(str(user.phone or "")),
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
            await transport.send_text("Выберите подходящую категорию:", self._kb.category_select_keyboard())
            return

        await transport.send_text(
            "Подтвердите категорию: нажмите кнопку «Да» или напишите «да». "
            "Если не подходит — «другое» или выберите другую.",
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
            categories=self._deps.classifier.categories(),
            label_resolver=self._deps.classifier.label,
        )
        if parsed_category is None:
            await transport.send_text(
                f"Не удалось определить категорию. Выберите кнопками ниже.\n{self._category_options_hint()}",
                self._kb.category_select_keyboard(),
            )
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
            await transport.send_text(self._build_report_correction_prompt(), None)
            return

        await transport.send_text(
            "Проверьте, пожалуйста, сводку и ответьте «да», если все верно, или «нет», если нужно исправить.",
            self._kb.report_confirm_keyboard(),
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
        correction = self._correction_flow.apply(data=data, extracted=extracted, text=text)
        updated = correction.data

        if correction.phone_to_sync:
            await self._deps.storage.update_user_phone(user.id, correction.phone_to_sync)
            user.phone = correction.phone_to_sync

        if correction.correction_field == "category" and correction.parsed_category is None:
            await self._save_snapshot(user.id, DialogStep.AWAITING_CATEGORY_SELECT, updated)
            await transport.send_text(
                "Выберите категорию кнопками ниже или напишите ее текстом.",
                self._kb.category_select_keyboard(),
            )
            return

        if correction.correction_field == "address" and not any(
            value is not None for value in (extracted.jk, extracted.house, extracted.entrance, extracted.apartment)
        ):
            await self._save_snapshot(user.id, DialogStep.AWAITING_REPORT_CORRECTION, updated)
            await transport.send_text(
                "Напишите адрес одним сообщением: дом, подъезд и квартиру. ЖК можно тоже указать, если нужно.",
                None,
            )
            return

        if correction.correction_field == "phone" and correction.phone_to_sync is None:
            await self._save_snapshot(user.id, DialogStep.AWAITING_REPORT_CORRECTION, updated)
            await transport.send_text("Напишите новый телефон в формате +7XXXXXXXXXX.", None)
            return

        if correction.correction_field == "problem" and not correction.has_structured_updates:
            await self._save_snapshot(user.id, DialogStep.AWAITING_REPORT_CORRECTION, updated)
            await transport.send_text("Напишите новое описание проблемы в 1-2 предложениях.", None)
            return

        if not correction.has_structured_updates and text.strip():
            if not await self._try_capture_problem_text(
                transport,
                user.id,
                updated,
                text,
                retry_step=DialogStep.AWAITING_REPORT_CORRECTION,
            ):
                return

        await self._send_report_confirmation(transport, user.id, updated)

    # ── Helpers ──

    def _resolve_voice_house(self, data: DialogSessionData) -> None:
        """Try to match extracted house number to a full address in the registry."""
        jk = str(data.jk or "").strip()
        raw_house = str(data.house or "").strip()
        if not jk or not raw_house:
            return

        # If the house is already a known full address, nothing to do
        if self._registry.find_house(raw_house):
            return

        # Try to match extracted house number (e.g. "5") to addresses in the JK
        houses = self._registry.houses_for_complex(jk)
        if not houses:
            houses = self._registry.standalone_houses

        for house in houses:
            # Match by house number in the address, e.g. "д.5" or "д.18, к.1"
            if raw_house in house.address or f"д.{raw_house}" in house.address or f"д. {raw_house}" in house.address:
                data.house = house.address
                # Auto-set entrance if only 1
                if house.entrances == 1 and not data.entrance:
                    data.entrance = "1"
                return

    def _get_current_house_list(self, data: DialogSessionData) -> list[HouseInfo]:
        jk = str(data.jk or "").strip()
        if jk == STANDALONE_JK_MARKER:
            return self._registry.standalone_houses
        houses = self._registry.houses_for_complex(jk)
        if houses:
            return houses
        return self._registry.standalone_houses

    async def _reset_to_new_request(self, transport: DialogTransport, user_id: int) -> None:
        await self._save_snapshot(user_id, DialogStep.AWAITING_JK, DialogSessionData())
        await transport.send_text(
            "Готова помочь с новой заявкой. Выберите, пожалуйста, ЖК:",
            self._kb.jk_keyboard(self._registry.complex_names, 0),
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
        await transport.send_text(text, self._kb.jk_keyboard(self._registry.complex_names, page=0))

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
            await transport.send_text(_PHONE_PROMPT_TEXT, None)
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
            await transport.send_text(_PHONE_PROMPT_TEXT, None)
            return

        await self._save_snapshot(user_id, DialogStep.AWAITING_PHONE_REUSE_CONFIRM, data)
        await transport.send_text(
            build_saved_phone_prompt(saved_phone),
            self._kb.phone_reuse_keyboard(saved_phone),
        )

    async def _handle_report_status_request(
        self,
        transport: DialogTransport,
        user: User,
        snapshot: DialogSnapshot,
    ) -> None:
        report = await self._report_lookup_service.get_latest_relevant_report(user.id)
        if report is not None:
            report = await self._report_lookup_service.enrich_with_bitrix(report)
        reply = self._report_lookup_service.build_reply(report)
        resume_prompt = build_resume_prompt(snapshot.step)
        if resume_prompt:
            reply = f"{reply}\n\n{resume_prompt}"
        await transport.send_text(reply, self._kb.back_to_menu_keyboard())

    async def _send_report_confirmation(
        self,
        transport: DialogTransport,
        user_id: int,
        data: DialogSessionData,
    ) -> None:
        await self._save_snapshot(user_id, DialogStep.AWAITING_REPORT_CONFIRM, data)
        await transport.send_text(self._build_report_review(data), self._kb.report_confirm_keyboard())

    async def _classify_problem(self, problem_text: str) -> ClassificationResult:
        return await self._category_service.classify(problem_text)

    async def _finalize_report(
        self,
        transport: DialogTransport,
        user: User,
        data: DialogSessionData,
    ) -> None:
        try:
            result = await self._report_finalizer.finalize_report(user=user, data=data)
        except ReportLimitExceeded as exc:
            await transport.send_text(f"⚠ Не удалось создать заявку: {exc.reason}", None)
            return
        reply_text = result.reply_text
        if self._deps.bitrix_service.enabled:
            bitrix_id = await self._report_finalizer.sync_bitrix_ticket(
                report=result.report,
                user=user,
                is_mass_incident=result.is_mass_incident,
                notify_user=False,
            )
            reply_text = await self._report_finalizer.build_created_reply_text(
                report=result.report,
                user=user,
                data=data,
                incident_message=result.confirmation.incident_message,
                bitrix_id=bitrix_id,
                bitrix_sync_outcome="synced" if bitrix_id else "failed",
            )
        await transport.send_text(reply_text, self._kb.new_report_keyboard())

    def _build_report_review(self, data: DialogSessionData) -> str:
        category = str(data.category or data.auto_category or "other")
        category_options_hint = self._category_options_hint() if category == "other" else None
        display_jk = data.jk if data.jk and data.jk not in (UNKNOWN_JK_VALUE, STANDALONE_JK_MARKER) else None
        mc = self._registry.management_company_for(data.house or "")
        return build_report_review(
            ReportReviewView(
                category_label=self._deps.classifier.label(category),
                jk=display_jk,
                house=data.house,
                entrance=data.entrance,
                apartment=data.apartment,
                phone=data.phone,
                problem_text=data.problem_text,
                category_options_hint=category_options_hint,
                mc_name=mc.name if mc else None,
                mc_dispatcher_phone=mc.dispatcher_phone if mc else None,
                mc_emergency_phone=mc.emergency_phone if mc else None,
            )
        )

    def _build_report_correction_prompt(self) -> str:
        return (
            "Напишите, что нужно исправить. Можно одним сообщением: адрес, телефон, описание проблемы "
            "или категорию. Потом я еще раз покажу сводку.\n"
            f"{self._category_options_hint()}\n"
            "Если хотите начать заново, напишите /new."
        )

    def _category_options_hint(self) -> str:
        labels = [
            label
            for code, label in CATEGORY_LABELS.items()
            if code != "other"
        ]
        return build_category_options_hint(labels)

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

    async def _upsert_user(self, telegram_id: int, display_name: str | None) -> User:
        return await self._deps.storage.upsert_user(telegram_id=telegram_id, name=display_name)

    async def _load_snapshot(self, user_id: int) -> DialogSnapshot:
        payload = await self._deps.storage.get_session(user_id)
        return DialogSnapshot(
            step=dialog_step(payload.step),
            data=DialogSessionData.from_mapping(payload.data),
        )

    async def _save_snapshot(self, user_id: int, step: DialogStep, data: DialogSessionData) -> None:
        await self._deps.storage.save_session(
            user_id=user_id,
            payload=SessionPayload(step=step.value, data=data.to_mapping()),
        )
