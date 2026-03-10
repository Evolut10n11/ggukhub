from __future__ import annotations

from collections.abc import Callable

from app.core.schemas import ReportLookupResult
from app.core.storage import Storage
from app.telegram.dialog.formatters import ReportLookupView, build_report_lookup_reply


class DialogReportLookupService:
    def __init__(self, storage: Storage, label_resolver: Callable[[str], str]):
        self._storage = storage
        self._label_resolver = label_resolver

    async def get_latest_relevant_report(self, user_id: int) -> ReportLookupResult | None:
        report = await self._storage.get_latest_active_report_summary(user_id)
        if report is not None:
            return report
        return await self._storage.get_latest_report_summary(user_id)

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
            )
        )
