from __future__ import annotations

from typing import Any

from app.bitrix.client import BitrixApiClient
from app.bitrix.models import (
    BitrixCommentPayloadInput,
    BitrixStatusUpdatePayloadInput,
    BitrixTicketPayloadInput,
    BitrixWebhookResult,
)
from app.bitrix.payloads import (
    build_add_comment_payload,
    build_create_ticket_payload,
    build_update_status_payload,
)
from app.bitrix.webhooks import parse_bitrix_event, verify_bitrix_secret
from app.config import Settings
from app.core.models import Report, User
from app.core.storage import Storage
from app.telegram.notifier import TelegramNotifier


class BitrixTicketService:
    def __init__(self, settings: Settings, client: BitrixApiClient):
        self._settings = settings
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._client.enabled

    async def create_ticket(self, report: Report, user: User) -> str:
        payload_input = BitrixTicketPayloadInput(
            local_report_id=report.id,
            telegram_id=user.telegram_id,
            title=f"Заявка УК #{report.id}",
            description=(
                f"{report.text}\n\n"
                f"Категория: {report.category}\n"
                f"ЖК: {report.jk or 'не указан'}\n"
                f"Адрес: {report.address}\n"
                f"Квартира: {report.apt}\n"
                f"Телефон: {report.phone}"
            ),
            jk=report.jk,
            address=report.address,
            category=report.category,
            phone=report.phone,
        )
        payload = build_create_ticket_payload(self._settings, payload_input)
        data = await self._client.call(self._settings.bitrix_ticket_method, payload)
        return self._client.extract_result_id(data)

    async def add_comment(self, bitrix_id: str, text: str) -> None:
        payload = build_add_comment_payload(
            BitrixCommentPayloadInput(
                bitrix_id=bitrix_id,
                text=text,
                entity_type=self._settings.bitrix_entity_type,
            )
        )
        _ = await self._client.call(self._settings.bitrix_comment_method, payload)

    async def update_status(self, bitrix_id: str, status: str) -> None:
        payload = build_update_status_payload(
            BitrixStatusUpdatePayloadInput(
                bitrix_id=bitrix_id,
                status=status,
                status_field=self._settings.bitrix_field_status,
            )
        )
        _ = await self._client.call(self._settings.bitrix_update_method, payload)


class BitrixWebhookService:
    def __init__(self, settings: Settings, storage: Storage, notifier: TelegramNotifier):
        self._settings = settings
        self._storage = storage
        self._notifier = notifier

    async def handle(self, payload: dict[str, Any], provided_secret: str | None) -> BitrixWebhookResult:
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

        return BitrixWebhookResult(
            accepted=signature_valid,
            event_id=event.id,
            event_type=parsed.event_type,
            bitrix_id=parsed.bitrix_id,
            status=parsed.status,
            telegram_notified=notified,
        )
