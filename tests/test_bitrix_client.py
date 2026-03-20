from __future__ import annotations

import httpx
import pytest

from app.bitrix.client import (
    BitrixApiClient,
    BitrixApiResponseError,
    BitrixConfigurationError,
    BitrixResponseFormatError,
    BitrixTransportError,
)
from app.config.settings import Settings


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="x",

        bitrix_webhook_url="https://bitrix.example/rest/1/webhook",
    )


@pytest.mark.asyncio
async def test_bitrix_client_reuses_async_client_and_closes_it() -> None:
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(status_code=200, json={"result": 123})

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))

    first = await client.call("crm.lead.add", {"fields": {"TITLE": "one"}})
    initial_client_id = id(client._client)
    second = await client.call("crm.lead.add", {"fields": {"TITLE": "two"}})

    assert first == {"result": 123}
    assert second == {"result": 123}
    assert len(requests) == 2
    assert id(client._client) == initial_client_id

    await client.close()
    assert client._client is None


def test_bitrix_client_uses_configured_timeout() -> None:
    settings = Settings(
        telegram_bot_token="x",

        bitrix_webhook_url="https://bitrix.example/rest/1/webhook",
        bitrix_timeout_seconds=7.5,
    )
    client = BitrixApiClient(settings)

    assert client.timeout_seconds == 7.5


@pytest.mark.asyncio
async def test_bitrix_client_raises_transport_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down", request=request)

    client = BitrixApiClient(_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(BitrixTransportError):
        await client.call("crm.lead.add", {"fields": {}})


@pytest.mark.asyncio
async def test_bitrix_client_raises_api_and_format_errors() -> None:
    async def api_error_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json={"error": "INVALID_TOKEN"})

    api_error_client = BitrixApiClient(_settings(), transport=httpx.MockTransport(api_error_handler))
    with pytest.raises(BitrixApiResponseError):
        await api_error_client.call("crm.lead.add", {"fields": {}})

    async def format_error_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, text="not json")

    format_error_client = BitrixApiClient(_settings(), transport=httpx.MockTransport(format_error_handler))
    with pytest.raises(BitrixResponseFormatError):
        await format_error_client.call("crm.lead.add", {"fields": {}})


@pytest.mark.asyncio
async def test_bitrix_client_raises_configuration_error_when_disabled() -> None:
    client = BitrixApiClient(Settings(telegram_bot_token="x"))

    with pytest.raises(BitrixConfigurationError):
        await client.call("crm.lead.add", {"fields": {}})
