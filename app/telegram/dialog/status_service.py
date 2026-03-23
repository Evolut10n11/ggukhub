from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from app.core.schemas import ReportLookupResult
from app.core.storage import Storage
from app.telegram.dialog.formatters import ReportLookupView, build_report_lookup_reply

if TYPE_CHECKING:
    from app.bitrix.service import BitrixTicketService

logger = logging.getLogger(__name__)


class DialogReportLookupService:
    def __init__(
        self,
        storage: Storage,
        label_resolver: Callable[[str], str],
        bitrix_service: BitrixTicketService | None = None,
    ):
        self._storage = storage
        self._label_resolver = label_resolver
        self._bitrix_service = bitrix_service

    async def get_latest_relevant_report(self, user_id: int) -> ReportLookupResult | None:
        report = await self._storage.get_latest_active_report_summary(user_id)
        if report is not None:
            return report
        return await self._storage.get_latest_report_summary(user_id)

    async def enrich_with_bitrix(self, report: ReportLookupResult) -> ReportLookupResult:
        if not self._bitrix_service or not self._bitrix_service.enabled or not report.bitrix_id:
            return report

        lead_info = await self._bitrix_service.get_lead(report.bitrix_id)
        if lead_info and lead_info.status_id:
            report.bitrix_status_id = lead_info.status_id
            report.bitrix_status_label = await self._bitrix_service.resolve_status_label(lead_info.status_id)
            report.bitrix_date_modify = lead_info.date_modify

        comments = await self._bitrix_service.get_comments(report.bitrix_id, limit=3)
        if comments:
            report.bitrix_comments = [
                {"comment": c.comment, "created": c.created}
                for c in comments
            ]

        return report

    def build_reply(self, report: ReportLookupResult | None) -> str:
        if report is None:
            return "Ранее зарегистрированных заявок не нашла."
        return build_report_lookup_reply(
            ReportLookupView(
                report_id=report.report_id,
                status=report.status,
                created_at=report.created_at,
                category_label=self._label_resolver(report.category),
                address=report.address,
                jk=report.jk,
                bitrix_id=report.bitrix_id,
                bitrix_status_label=report.bitrix_status_label,
                bitrix_date_modify=report.bitrix_date_modify,
                bitrix_comments=report.bitrix_comments,
            )
        )
