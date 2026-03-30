from __future__ import annotations

import logging
import time
from typing import Any

from app.bitrix.client import BitrixApiClient, BitrixClientError
from app.core.enums import report_status_label
from app.bitrix.formatters import build_ticket_description, build_ticket_title
from app.bitrix.models import (
    BitrixCommentPayloadInput,
    BitrixContactPayloadInput,
    BitrixLeadContactLinkInput,
    BitrixLeadGetPayloadInput,
    BitrixLeadInfo,
    BitrixNotifyPayloadInput,
    BitrixStatusItem,
    BitrixStatusUpdatePayloadInput,
    BitrixTicketPayloadInput,
    BitrixTimelineComment,
    BitrixWebhookResult,
)
from app.bitrix.payloads import (
    build_add_comment_payload,
    build_comment_list_payload,
    build_contact_add_payload,
    build_create_ticket_payload,
    build_find_contact_by_phone_payload,
    build_im_notify_payload,
    build_lead_contact_link_payload,
    build_lead_fields_payload,
    build_lead_get_payload,
    build_status_list_payload,
    build_update_status_payload,
)
from app.bitrix.webhooks import parse_bitrix_event, verify_bitrix_secret
from app.config import Settings
from app.core.models import Report, User
from app.core.storage import Storage
from app.telegram.notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class BitrixTicketService:
    def __init__(self, settings: Settings, client: BitrixApiClient):
        self._settings = settings
        self._client = client
        self._status_cache: list[BitrixStatusItem] = []
        self._status_cache_expires_at: float = 0.0

    @property
    def enabled(self) -> bool:
        return self._client.enabled

    @property
    def timeout_seconds(self) -> float:
        return self._client.timeout_seconds

    async def create_ticket(self, report: Report, user: User, contact_id: str | None = None) -> str:
        payload_input = BitrixTicketPayloadInput(
            local_report_id=report.id,
            telegram_id=user.telegram_id,
            title=build_ticket_title(report),
            description=build_ticket_description(report),
            reporter_name=user.name,
            jk=report.jk,
            address=report.address,
            category=report.category,
            phone=report.phone,
            apartment=report.apt,
            contact_id=contact_id,
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

    # --- Feature 1: crm.lead.get ---

    async def get_lead(self, bitrix_id: str) -> BitrixLeadInfo | None:
        try:
            payload = build_lead_get_payload(
                BitrixLeadGetPayloadInput(
                    bitrix_id=bitrix_id,
                    select_fields=["ID", "STATUS_ID", "TITLE", "DATE_MODIFY"],
                )
            )
            data = await self._client.call("crm.lead.get", payload)
            result = data.get("result", {})
            if not isinstance(result, dict):
                return None
            return BitrixLeadInfo(
                bitrix_id=str(result.get("ID", bitrix_id)),
                status_id=result.get("STATUS_ID"),
                title=result.get("TITLE"),
                date_modify=result.get("DATE_MODIFY"),
            )
        except BitrixClientError as exc:
            logger.warning("Failed to get lead %s from Bitrix: %s", bitrix_id, exc)
            return None

    # --- Feature 2: crm.status.entity.items ---

    async def fetch_status_dictionary(self) -> list[BitrixStatusItem]:
        now = time.monotonic()
        if self._status_cache and now < self._status_cache_expires_at:
            return self._status_cache

        try:
            payload = build_status_list_payload("STATUS")
            data = await self._client.call("crm.status.entity.items", payload)
            items = data.get("result", [])
            if not isinstance(items, list):
                return self._status_cache
            self._status_cache = [
                BitrixStatusItem(
                    status_id=str(item.get("STATUS_ID", "")),
                    name=str(item.get("NAME", "")),
                    sort=int(item.get("SORT", 0)),
                )
                for item in items
                if isinstance(item, dict) and item.get("STATUS_ID")
            ]
            self._status_cache_expires_at = now + self._settings.bitrix_status_cache_ttl_seconds
        except BitrixClientError as exc:
            logger.warning("Failed to fetch status dictionary: %s", exc)

        return self._status_cache

    async def resolve_status_label(self, status_id: str) -> str:
        statuses = await self.fetch_status_dictionary()
        for item in statuses:
            if item.status_id == status_id:
                return item.name
        return status_id

    # --- Feature 3: crm.timeline.comment.list ---

    async def get_comments(self, bitrix_id: str, limit: int = 5) -> list[BitrixTimelineComment]:
        try:
            payload = build_comment_list_payload(bitrix_id, self._settings.bitrix_entity_type_id)
            data = await self._client.call("crm.timeline.comment.list", payload)
            items = data.get("result", [])
            if not isinstance(items, list):
                return []
            comments = []
            for item in items[:limit]:
                if not isinstance(item, dict):
                    continue
                comments.append(
                    BitrixTimelineComment(
                        id=str(item.get("ID", "")),
                        comment=str(item.get("COMMENT", "")),
                        created=str(item.get("CREATED", "")),
                    )
                )
            return comments
        except BitrixClientError as exc:
            logger.warning("Failed to get comments for lead %s: %s", bitrix_id, exc)
            return []

    # --- Feature 4: crm.lead.fields ---

    async def validate_fields(self) -> list[str]:
        configured_fields = [
            self._settings.bitrix_field_jk,
            self._settings.bitrix_field_address,
            self._settings.bitrix_field_category,
            self._settings.bitrix_field_telegram_id,
            self._settings.bitrix_field_local_report_id,
        ]
        try:
            data = await self._client.call("crm.lead.fields", build_lead_fields_payload())
            result = data.get("result", {})
            if not isinstance(result, dict):
                logger.warning("Unexpected crm.lead.fields response format")
                return []
            available = set(result.keys())
            missing = [f for f in configured_fields if f.startswith("UF_") and f not in available]
            for field_name in missing:
                logger.warning("Bitrix custom field %s not found in crm.lead.fields", field_name)
            return missing
        except BitrixClientError as exc:
            logger.warning("Failed to validate Bitrix fields: %s", exc)
            return []

    # --- Feature 5: im.notify.system.add ---

    async def notify_manager(self, user_id: int, message: str) -> bool:
        try:
            payload = build_im_notify_payload(
                BitrixNotifyPayloadInput(user_id=user_id, message=message)
            )
            await self._client.call("im.notify.system.add", payload)
            return True
        except BitrixClientError as exc:
            logger.warning("Failed to notify manager %s: %s", user_id, exc)
            return False

    async def notify_managers_urgent(self, report: Report) -> None:
        if not self._settings.bitrix_urgent_notify_enabled:
            return
        raw_ids = self._settings.bitrix_manager_user_ids
        if not raw_ids.strip():
            return
        manager_ids = [int(uid.strip()) for uid in raw_ids.split(",") if uid.strip().isdigit()]
        message = f"Срочная заявка №{report.id}: {report.category} — {report.address}"
        for uid in manager_ids:
            await self.notify_manager(uid, message)

    # --- Feature 6: crm.duplicate.findbycomm + crm.contact.add ---

    async def find_contact_by_phone(self, phone: str) -> str | None:
        try:
            payload = build_find_contact_by_phone_payload(phone)
            data = await self._client.call("crm.duplicate.findbycomm", payload)
            result = data.get("result", {})
            contacts = result.get("CONTACT", [])
            if contacts:
                return str(contacts[0])
            return None
        except BitrixClientError as exc:
            logger.warning("Failed to find Bitrix contact by phone: %s", exc)
            return None

    async def create_contact(self, name: str, phone: str) -> str | None:
        try:
            payload = build_contact_add_payload(
                BitrixContactPayloadInput(name=name, phone=phone)
            )
            data = await self._client.call("crm.contact.add", payload)
            return self._client.extract_result_id(data)
        except BitrixClientError as exc:
            logger.warning("Failed to create Bitrix contact: %s", exc)
            return None

    async def link_contact_to_lead(self, lead_id: str, contact_id: str) -> bool:
        try:
            payload = build_lead_contact_link_payload(
                BitrixLeadContactLinkInput(lead_id=lead_id, contact_id=contact_id)
            )
            await self._client.call("crm.lead.contact.add", payload)
            return True
        except BitrixClientError as exc:
            logger.warning("Failed to link contact %s to lead %s: %s", contact_id, lead_id, exc)
            return False


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
                text=f"Ваша заявка №{report.id} обновлена.\nСтатус: {report_status_label(parsed.status)}",
            )

        return BitrixWebhookResult(
            accepted=signature_valid,
            event_id=event.id,
            event_type=parsed.event_type,
            bitrix_id=parsed.bitrix_id,
            status=parsed.status,
            telegram_notified=notified,
        )
