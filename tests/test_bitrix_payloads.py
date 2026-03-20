from __future__ import annotations

from app.bitrix.models import (
    BitrixCommentPayloadInput,
    BitrixStatusUpdatePayloadInput,
    BitrixTicketPayloadInput,
)
from app.bitrix.payloads import (
    build_add_comment_payload,
    build_create_ticket_payload,
    build_update_status_payload,
)
from app.config.settings import Settings


def test_build_create_ticket_payload_maps_domain_fields() -> None:
    settings = Settings(
        telegram_bot_token="x",

        bitrix_webhook_url="https://bitrix.example/rest/1/webhook",
    )
    payload = build_create_ticket_payload(
        settings,
        BitrixTicketPayloadInput(
            local_report_id=42,
            telegram_id=123456789,
            title="Заявка УК #42",
            description="Описание",
            jk="Pride Park",
            address="дом 5, подъезд 3, кв 78",
            category="elevator",
            phone="+79990001122",
        ),
    )

    fields = payload["fields"]
    assert fields[settings.bitrix_field_title] == "Заявка УК #42"
    assert fields[settings.bitrix_field_description] == "Описание"
    assert fields[settings.bitrix_field_jk] == "Pride Park"
    assert fields[settings.bitrix_field_address] == "дом 5, подъезд 3, кв 78"
    assert fields[settings.bitrix_field_category] == "elevator"
    assert fields[settings.bitrix_field_telegram_id] == "123456789"
    assert fields[settings.bitrix_field_local_report_id] == "42"
    assert fields["PHONE"] == [{"VALUE": "+79990001122", "VALUE_TYPE": "WORK"}]


def test_build_add_comment_payload_converts_numeric_bitrix_id() -> None:
    payload = build_add_comment_payload(
        BitrixCommentPayloadInput(
            bitrix_id="7001",
            text="Комментарий",
            entity_type="lead",
        )
    )

    assert payload == {
        "fields": {
            "ENTITY_ID": 7001,
            "ENTITY_TYPE": "lead",
            "COMMENT": "Комментарий",
        }
    }


def test_build_update_status_payload_uses_configured_status_field() -> None:
    payload = build_update_status_payload(
        BitrixStatusUpdatePayloadInput(
            bitrix_id="B24-7001",
            status="IN_PROGRESS",
            status_field="STATUS_ID",
        )
    )

    assert payload == {
        "id": "B24-7001",
        "fields": {"STATUS_ID": "IN_PROGRESS"},
    }
