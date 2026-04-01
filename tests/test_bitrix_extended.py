"""Tests for extended Bitrix24 API integration (Features 1-6)."""
from __future__ import annotations

import httpx
import pytest

from app.bitrix.client import BitrixApiClient
from app.bitrix.models import (
    BitrixContactPayloadInput,
    BitrixLeadContactLinkInput,
    BitrixLeadGetPayloadInput,
    BitrixNotifyPayloadInput,
)
from app.bitrix.payloads import (
    build_comment_list_payload,
    build_contact_add_payload,
    build_im_notify_payload,
    build_lead_contact_link_payload,
    build_lead_fields_payload,
    build_lead_get_payload,
    build_status_list_payload,
)
from app.bitrix.service import BitrixTicketService
from app.config.settings import Settings


def _settings(**overrides: object) -> Settings:
    defaults = {
        "telegram_bot_token": "x",
        "bitrix_webhook_url": "https://bitrix.example/rest/1/webhook",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_build_url_uses_request_override() -> None:
    settings = _settings(
        bitrix_webhook_url="https://bitrix.example/rest/1/webhook",
        bitrix_request_override_url="https://webhook.site/test-token",
    )
    client = BitrixApiClient(settings)

    url, headers = client.build_url("crm.lead.add")

    assert url == "https://webhook.site/test-token"
    assert headers == {}


# --- Payload builder tests ---


def test_build_lead_get_payload() -> None:
    payload = build_lead_get_payload(
        BitrixLeadGetPayloadInput(bitrix_id="100", select_fields=["ID", "STATUS_ID"])
    )
    assert payload == {"id": 100, "select": ["ID", "STATUS_ID"]}


def test_build_lead_get_payload_non_numeric() -> None:
    payload = build_lead_get_payload(
        BitrixLeadGetPayloadInput(bitrix_id="B24-100", select_fields=["ID"])
    )
    assert payload == {"id": "B24-100", "select": ["ID"]}


def test_build_status_list_payload() -> None:
    payload = build_status_list_payload("STATUS")
    assert payload == {"entityId": "STATUS"}


def test_build_comment_list_payload() -> None:
    payload = build_comment_list_payload("100", 1)
    assert payload == {"entityId": 100, "entityTypeId": 1}


def test_build_lead_fields_payload() -> None:
    assert build_lead_fields_payload() == {}


def test_build_im_notify_payload() -> None:
    payload = build_im_notify_payload(
        BitrixNotifyPayloadInput(user_id=42, message="Urgent!")
    )
    assert payload == {"to": 42, "message": "Urgent!", "type": "SYSTEM"}


def test_build_contact_add_payload() -> None:
    payload = build_contact_add_payload(
        BitrixContactPayloadInput(name="Иванов", phone="+79991112233")
    )
    assert payload["fields"]["NAME"] == "Иванов"
    assert payload["fields"]["PHONE"] == [{"VALUE": "+79991112233", "VALUE_TYPE": "WORK"}]


def test_build_lead_contact_link_payload() -> None:
    payload = build_lead_contact_link_payload(
        BitrixLeadContactLinkInput(lead_id="100", contact_id="200")
    )
    assert payload == {"id": 100, "fields": {"CONTACT_ID": 200}}


# --- Service method tests ---


@pytest.mark.asyncio
async def test_get_lead_returns_lead_info() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "result": {
                    "ID": "100",
                    "STATUS_ID": "IN_PROCESS",
                    "TITLE": "Test Lead",
                    "DATE_MODIFY": "2026-03-23T10:00:00",
                }
            },
        )

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))
    service = BitrixTicketService(_settings(), client)

    info = await service.get_lead("100")
    assert info is not None
    assert info.bitrix_id == "100"
    assert info.status_id == "IN_PROCESS"
    assert info.title == "Test Lead"
    assert info.date_modify == "2026-03-23T10:00:00"


@pytest.mark.asyncio
async def test_get_lead_returns_none_on_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json={"error": "NOT_FOUND"})

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))
    service = BitrixTicketService(_settings(), client)

    info = await service.get_lead("999")
    assert info is None


@pytest.mark.asyncio
async def test_fetch_status_dictionary() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "result": [
                    {"STATUS_ID": "NEW", "NAME": "Новый", "SORT": 10},
                    {"STATUS_ID": "IN_PROCESS", "NAME": "В работе", "SORT": 20},
                ]
            },
        )

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))
    service = BitrixTicketService(_settings(), client)

    statuses = await service.fetch_status_dictionary()
    assert len(statuses) == 2
    assert statuses[0].status_id == "NEW"
    assert statuses[0].name == "Новый"
    assert statuses[1].status_id == "IN_PROCESS"


@pytest.mark.asyncio
async def test_fetch_status_dictionary_uses_cache() -> None:
    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            status_code=200,
            json={"result": [{"STATUS_ID": "NEW", "NAME": "Новый", "SORT": 10}]},
        )

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))
    service = BitrixTicketService(_settings(), client)

    await service.fetch_status_dictionary()
    await service.fetch_status_dictionary()
    assert call_count == 1


@pytest.mark.asyncio
async def test_resolve_status_label() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "result": [
                    {"STATUS_ID": "NEW", "NAME": "Новый", "SORT": 10},
                    {"STATUS_ID": "IN_PROCESS", "NAME": "В работе", "SORT": 20},
                ]
            },
        )

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))
    service = BitrixTicketService(_settings(), client)

    label = await service.resolve_status_label("IN_PROCESS")
    assert label == "В работе"

    unknown = await service.resolve_status_label("UNKNOWN")
    assert unknown == "UNKNOWN"


@pytest.mark.asyncio
async def test_get_comments() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "result": [
                    {"ID": "1", "COMMENT": "Мастер выехал", "CREATED": "2026-03-23T10:00:00"},
                    {"ID": "2", "COMMENT": "Проблема устранена", "CREATED": "2026-03-23T11:00:00"},
                ]
            },
        )

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))
    service = BitrixTicketService(_settings(), client)

    comments = await service.get_comments("100")
    assert len(comments) == 2
    assert comments[0].comment == "Мастер выехал"
    assert comments[1].comment == "Проблема устранена"


@pytest.mark.asyncio
async def test_get_comments_returns_empty_on_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json={"error": "ACCESS_DENIED"})

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))
    service = BitrixTicketService(_settings(), client)

    comments = await service.get_comments("100")
    assert comments == []


@pytest.mark.asyncio
async def test_validate_fields_detects_missing() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "result": {
                    "ID": {"type": "integer"},
                    "TITLE": {"type": "string"},
                    "UF_CRM_JK": {"type": "string"},
                    # Missing: UF_CRM_ADDRESS, UF_CRM_CATEGORY, etc.
                }
            },
        )

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))
    service = BitrixTicketService(_settings(), client)

    missing = await service.validate_fields()
    assert "UF_CRM_ADDRESS" in missing
    assert "UF_CRM_CATEGORY" in missing
    assert "UF_CRM_JK" not in missing


@pytest.mark.asyncio
async def test_validate_fields_all_present() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "result": {
                    "UF_CRM_JK": {"type": "string"},
                    "UF_CRM_ADDRESS": {"type": "string"},
                    "UF_CRM_CATEGORY": {"type": "string"},
                    "UF_CRM_TELEGRAM_ID": {"type": "string"},
                    "UF_CRM_LOCAL_REPORT_ID": {"type": "string"},
                }
            },
        )

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))
    service = BitrixTicketService(_settings(), client)

    missing = await service.validate_fields()
    assert missing == []


@pytest.mark.asyncio
async def test_notify_manager_success() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json={"result": True})

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))
    service = BitrixTicketService(_settings(), client)

    result = await service.notify_manager(42, "Test notification")
    assert result is True


@pytest.mark.asyncio
async def test_notify_manager_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json={"error": "USER_NOT_FOUND"})

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))
    service = BitrixTicketService(_settings(), client)

    result = await service.notify_manager(999, "Test")
    assert result is False


@pytest.mark.asyncio
async def test_create_contact() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json={"result": 500})

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))
    service = BitrixTicketService(_settings(), client)

    contact_id = await service.create_contact("Иванов", "+79991112233")
    assert contact_id == "500"


@pytest.mark.asyncio
async def test_link_contact_to_lead() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json={"result": True})

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))
    service = BitrixTicketService(_settings(), client)

    result = await service.link_contact_to_lead("100", "500")
    assert result is True


# --- Formatter tests ---


def test_report_lookup_reply_with_bitrix_enrichment() -> None:
    from datetime import datetime, timezone

    from app.telegram.dialog.formatters import ReportLookupView, build_report_lookup_reply

    view = ReportLookupView(
        report_id=42,
        status="new",
        created_at=datetime(2026, 3, 23, 10, 0, tzinfo=timezone.utc),
        category_label="Лифт",
        address="дом 5, кв 78",
        jk="Pride Park",
        bitrix_id="B24-100",
        bitrix_status_label="В работе",
        bitrix_date_modify="2026-03-23T12:00:00",
        bitrix_comments=[
            {"comment": "Мастер выехал"},
            {"comment": "Проблема устранена"},
        ],
    )

    reply = build_report_lookup_reply(view)
    assert "Номер: B24-100" in reply
    assert "Статус обработки: В работе" in reply
    assert "Обновлена: 2026-03-23T12:00:00" in reply
    assert "Последние комментарии:" in reply
    assert "Мастер выехал" in reply
    assert "Проблема устранена" in reply


def test_report_lookup_reply_without_bitrix_enrichment() -> None:
    from datetime import datetime, timezone

    from app.telegram.dialog.formatters import ReportLookupView, build_report_lookup_reply

    view = ReportLookupView(
        report_id=42,
        status="new",
        created_at=datetime(2026, 3, 23, 10, 0, tzinfo=timezone.utc),
        category_label="Лифт",
        address="дом 5, кв 78",
        jk=None,
        bitrix_id=None,
    )

    reply = build_report_lookup_reply(view)
    assert "Номер: 42" in reply
    assert "Статус в Bitrix24" not in reply
    assert "Последние комментарии" not in reply
