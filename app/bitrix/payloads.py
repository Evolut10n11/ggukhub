from __future__ import annotations

from typing import Any

from app.bitrix.models import (
    BitrixCommentPayloadInput,
    BitrixContactPayloadInput,
    BitrixLeadContactLinkInput,
    BitrixLeadGetPayloadInput,
    BitrixNotifyPayloadInput,
    BitrixStatusUpdatePayloadInput,
    BitrixTicketPayloadInput,
)
from app.config import Settings


def build_create_ticket_payload(
    settings: Settings,
    payload_input: BitrixTicketPayloadInput,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        settings.bitrix_field_title: payload_input.title,
        "SOURCE_ID": settings.bitrix_lead_source_id,
        settings.bitrix_field_description: payload_input.description,
        "ASSIGNED_BY_ID": settings.bitrix_deal_assigned_by_id,
        settings.bitrix_field_jk: payload_input.jk or "",
        settings.bitrix_field_address: payload_input.address,
        settings.bitrix_field_category: payload_input.category,
        settings.bitrix_field_telegram_id: str(payload_input.telegram_id),
        settings.bitrix_field_local_report_id: str(payload_input.local_report_id),
    }
    fields.update(_build_reporter_fields(payload_input.reporter_name))

    if payload_input.apartment:
        fields[settings.bitrix_field_apartment] = payload_input.apartment

    if payload_input.phone:
        fields[settings.bitrix_field_phone] = [
            {"VALUE": payload_input.phone, "VALUE_TYPE": "WORK"},
        ]

    if payload_input.contact_id:
        fields["CONTACT_ID"] = payload_input.contact_id

    return {"fields": fields}


def _build_reporter_fields(reporter_name: str | None) -> dict[str, str]:
    parts = [part for part in str(reporter_name or "").strip().split() if part]
    if not parts:
        return {}
    if len(parts) == 1:
        return {"NAME": parts[0]}
    if len(parts) == 2:
        return {"NAME": parts[0], "LAST_NAME": parts[1]}
    if len(parts) == 3 and _looks_like_patronymic(parts[2]):
        return {
            "LAST_NAME": parts[0],
            "NAME": parts[1],
            "SECOND_NAME": parts[2],
        }
    if len(parts) >= 3 and _looks_like_patronymic(parts[1]):
        return {
            "NAME": parts[0],
            "SECOND_NAME": " ".join(parts[1:-1]),
            "LAST_NAME": parts[-1],
        }
    return {
        "NAME": parts[0],
        "SECOND_NAME": " ".join(parts[1:-1]),
        "LAST_NAME": parts[-1],
    }


def _looks_like_patronymic(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized.endswith(
        (
            "ич",
            "вич",
            "евич",
            "ович",
            "евич",
            "оглы",
            "кызы",
            "ична",
            "вна",
            "евна",
            "овна",
        )
    )


def build_add_comment_payload(payload_input: BitrixCommentPayloadInput) -> dict[str, Any]:
    return {
        "fields": {
            "ENTITY_ID": int(payload_input.bitrix_id) if payload_input.bitrix_id.isdigit() else payload_input.bitrix_id,
            "ENTITY_TYPE": payload_input.entity_type,
            "COMMENT": payload_input.text,
        }
    }


def build_update_status_payload(payload_input: BitrixStatusUpdatePayloadInput) -> dict[str, Any]:
    return {
        "id": int(payload_input.bitrix_id) if payload_input.bitrix_id.isdigit() else payload_input.bitrix_id,
        "fields": {payload_input.status_field: payload_input.status},
    }


def build_lead_get_payload(payload_input: BitrixLeadGetPayloadInput) -> dict[str, Any]:
    return {
        "id": int(payload_input.bitrix_id) if payload_input.bitrix_id.isdigit() else payload_input.bitrix_id,
        "select": payload_input.select_fields,
    }


def build_status_list_payload(entity_id: str) -> dict[str, Any]:
    return {"entityId": entity_id}


def build_comment_list_payload(bitrix_id: str, entity_type_id: int) -> dict[str, Any]:
    return {
        "entityId": int(bitrix_id) if bitrix_id.isdigit() else bitrix_id,
        "entityTypeId": entity_type_id,
    }


def build_lead_fields_payload() -> dict[str, Any]:
    return {}


def build_im_notify_payload(payload_input: BitrixNotifyPayloadInput) -> dict[str, Any]:
    return {
        "to": payload_input.user_id,
        "message": payload_input.message,
        "type": "SYSTEM",
    }


def build_find_contact_by_phone_payload(phone: str) -> dict[str, Any]:
    return {
        "type": "PHONE",
        "values": [phone],
        "entity_type": "CONTACT",
    }


def build_contact_add_payload(payload_input: BitrixContactPayloadInput) -> dict[str, Any]:
    return {
        "fields": {
            "NAME": payload_input.name,
            "PHONE": [{"VALUE": payload_input.phone, "VALUE_TYPE": "WORK"}],
        },
    }


def build_lead_contact_link_payload(payload_input: BitrixLeadContactLinkInput) -> dict[str, Any]:
    return {
        "id": int(payload_input.lead_id) if payload_input.lead_id.isdigit() else payload_input.lead_id,
        "fields": {
            "CONTACT_ID": int(payload_input.contact_id) if payload_input.contact_id.isdigit() else payload_input.contact_id,
        },
    }
