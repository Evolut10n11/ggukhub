from __future__ import annotations

from enum import Enum

from app.core.utils import normalize_text


class ReportStatus(str, Enum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class IncidentStatus(str, Enum):
    ACTIVE = "active"


class ReportAuditStage(str, Enum):
    REPORT_CREATED = "report_created"
    BITRIX_SYNC_FAILED = "bitrix_sync_failed"
    BITRIX_SYNCED = "bitrix_synced"


class BitrixSyncStatus(str, Enum):
    FAILED = "failed"
    SYNCED = "synced"


_REPORT_STATUS_LABELS: dict[str, str] = {
    "new": "Принята",
    "in_progress": "В работе",
    "closed": "Закрыта",
    "done": "Выполнена",
    "resolved": "Решена",
    "completed": "Выполнена",
    "cancelled": "Отменена",
}

_CLOSED_REPORT_STATUS_TOKENS = frozenset(
    {
        "closed",
        "done",
        "resolved",
        "completed",
        "cancelled",
        "закрыт",
        "выполнен",
        "решен",
        "отменен",
    }
)


def report_status_label(status: str | None) -> str:
    if not status:
        return "Не указан"
    normalized = normalize_text(status)
    label = _REPORT_STATUS_LABELS.get(normalized)
    if label:
        return label
    return status


def is_active_report_status(status: str | None) -> bool:
    value = normalize_text(status or "")
    if not value:
        return True
    return not any(token in value for token in _CLOSED_REPORT_STATUS_TOKENS)
