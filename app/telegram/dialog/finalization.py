from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.bitrix.client import BitrixClientError
from app.bitrix.service import BitrixTicketService
from app.core.enums import BitrixSyncStatus, ReportAuditStage
from app.core.models import Report, User
from app.core.regulation import REGULATION_VERSION, build_bitrix_audit_payload, build_report_composition_payload
from app.core.schemas import ReportAuditCreate, ReportCreate
from app.core.storage import Storage
from app.core.utils import build_address, compose_scope_key
from app.incidents.service import IncidentService
from app.responders.base import BaseResponder
from app.telegram.constants import UNKNOWN_JK_VALUE
from app.telegram.dialog.formatters import (
    CreatedReportReplyParts,
    ReportSummaryView,
    build_created_report_reply,
    build_report_summary,
)
from app.telegram.dialog.models import DialogSessionData, FinalizedReportDraft
from app.telegram.notifier import TelegramNotifier

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DialogReportFinalizationResult:
    report: Report
    reply_text: str
    is_mass_incident: bool


class DialogReportFinalizer:
    def __init__(
        self,
        *,
        storage: Storage,
        incidents: IncidentService,
        responder: BaseResponder,
        bitrix_service: BitrixTicketService,
        notifier: TelegramNotifier,
        label_resolver: Callable[[str], str],
    ) -> None:
        self._storage = storage
        self._incidents = incidents
        self._responder = responder
        self._bitrix_service = bitrix_service
        self._notifier = notifier
        self._label_resolver = label_resolver

    async def finalize_report(self, *, user: User, data: DialogSessionData) -> DialogReportFinalizationResult:
        draft = self.build_report_draft(data, user)
        report = await self._storage.create_report(
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

        incident = await self._incidents.evaluate_report(report)
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
            category_label=self._label_resolver(draft.category),
            is_mass_incident=incident.is_mass,
            incident_id=incident.incident_id,
        )
        await self._store_audit_log(
            report_id=report.id,
            stage=ReportAuditStage.REPORT_CREATED.value,
            payload=composition_payload,
        )

        generated = await self._responder.build_report_created(local_id=report.id, bitrix_id=None)
        summary = build_report_summary(
            ReportSummaryView(
                report_id=report.id,
                category_label=self._label_resolver(draft.category),
                jk=draft.jk,
                house=draft.house,
                entrance=draft.entrance,
                apartment=draft.apartment,
                bitrix_enabled=self._bitrix_service.enabled,
            )
        )
        reply_text = build_created_report_reply(
            CreatedReportReplyParts(
                standard_reply=generated.text,
                summary=summary,
                incident_message=incident.public_message if incident.is_mass else None,
                incident_report_id=report.id if incident.is_mass else None,
                include_missing_jk_note=draft.jk is None,
            )
        )
        return DialogReportFinalizationResult(
            report=report,
            reply_text=reply_text,
            is_mass_incident=incident.is_mass,
        )

    async def sync_bitrix_ticket(
        self,
        *,
        report: Report,
        user: User,
        is_mass_incident: bool,
    ) -> None:
        try:
            bitrix_id = await self._bitrix_service.create_ticket(report=report, user=user)
            await self._storage.set_report_bitrix_id(report.id, bitrix_id)
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
            await self._notifier.send_message(
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
        await self._notifier.send_message(telegram_id=user.telegram_id, text=followup)

    @staticmethod
    def build_report_draft(data: DialogSessionData, user: User) -> FinalizedReportDraft:
        _ = user
        jk_value = str(data.jk or "").strip()
        jk = jk_value if jk_value and jk_value != UNKNOWN_JK_VALUE else None

        house = str(data.house or "").strip()
        entrance = str(data.entrance or "").strip() or None
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

    async def _store_audit_log(
        self,
        *,
        report_id: int,
        stage: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            await self._storage.create_report_audit(
                ReportAuditCreate(
                    report_id=report_id,
                    stage=stage,
                    regulation_version=REGULATION_VERSION,
                    payload=payload,
                )
            )
        except Exception as error:
            logger.warning("Report audit log save failed for report %s at stage %s: %s", report_id, stage, error)
