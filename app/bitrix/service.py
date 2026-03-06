from __future__ import annotations

from typing import Any

from app.bitrix.webhooks import parse_bitrix_event, verify_bitrix_secret
from app.config import Settings
from app.core.storage import Storage
from app.telegram.notifier import TelegramNotifier


class BitrixWebhookService:
    def __init__(self, settings: Settings, storage: Storage, notifier: TelegramNotifier):
        self._settings = settings
        self._storage = storage
        self._notifier = notifier

    async def handle(self, payload: dict[str, Any], provided_secret: str | None) -> dict[str, Any]:
        signature_valid = verify_bitrix_secret(
            payload=payload,
            provided_secret=provided_secret,
            expected_secret=self._settings.bitrix_shared_secret,
        )
        parsed = parse_bitrix_event(payload)

        report_id: int | None = None
        report_with_user = None
        if parsed.bitrix_id:
            report_with_user = await self._storage.get_report_with_user_by_bitrix_id(parsed.bitrix_id)
            if report_with_user:
                report_id = report_with_user[0].id

        if signature_valid and parsed.bitrix_id and parsed.status:
            _ = await self._storage.update_report_status_by_bitrix_id(parsed.bitrix_id, parsed.status)

        event = await self._storage.create_bitrix_event(
            event_type=parsed.event_type,
            payload=payload,
            signature_valid=signature_valid,
            bitrix_id=parsed.bitrix_id,
            status=parsed.status,
            report_id=report_id,
        )

        notified = False
        if signature_valid and parsed.status and report_with_user:
            report, user = report_with_user
            notified = await self._notifier.send_message(
                telegram_id=user.telegram_id,
                text=f"Ваша заявка №{report.id} обновлена: {parsed.status}",
            )

        return {
            "accepted": signature_valid,
            "event_id": event.id,
            "event_type": parsed.event_type,
            "bitrix_id": parsed.bitrix_id,
            "status": parsed.status,
            "telegram_notified": notified,
        }

