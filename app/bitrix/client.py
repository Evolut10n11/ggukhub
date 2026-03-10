from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings


class BitrixClientError(RuntimeError):
    pass


class BitrixConfigurationError(BitrixClientError):
    pass


class BitrixTransportError(BitrixClientError):
    pass


class BitrixHttpStatusError(BitrixClientError):
    pass


class BitrixApiResponseError(BitrixClientError):
    pass


class BitrixResponseFormatError(BitrixClientError):
    pass


class BitrixApiClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self._settings = settings
        self._transport = transport
        self._client = client
        self._owns_client = client is None

    @property
    def enabled(self) -> bool:
        return self._settings.bitrix_enabled

    def build_url(self, method: str) -> tuple[str, dict[str, str]]:
        if self._settings.bitrix_webhook_url:
            base = self._settings.bitrix_webhook_url.rstrip("/")
            return f"{base}/{method}.json", {}
        if self._settings.bitrix_rest_url and self._settings.bitrix_token:
            base = self._settings.bitrix_rest_url.rstrip("/")
            return f"{base}/{method}.json", {"Authorization": f"Bearer {self._settings.bitrix_token}"}
        raise BitrixConfigurationError("Bitrix is not configured")

    async def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise BitrixConfigurationError("Bitrix integration is disabled")

        url, headers = self.build_url(method)
        client = self._get_client()

        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise BitrixHttpStatusError(f"Bitrix HTTP error: {error}") from error
        except httpx.HTTPError as error:
            raise BitrixTransportError(f"Bitrix transport error: {error}") from error

        try:
            data = response.json()
        except ValueError as error:
            raise BitrixResponseFormatError("Bitrix returned invalid JSON") from error
        if not isinstance(data, dict):
            raise BitrixResponseFormatError("Bitrix response must be a JSON object")
        if "error" in data:
            raise BitrixApiResponseError(str(data.get("error_description") or data["error"]))
        return data

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def extract_result_id(data: dict[str, Any]) -> str:
        result = data.get("result")
        if isinstance(result, (int, str)):
            return str(result)
        if isinstance(result, dict):
            for key in ("ID", "id", "item", "result"):
                value = result.get(key)
                if value is not None:
                    return str(value)
        raise BitrixResponseFormatError("Cannot extract Bitrix id from response")

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                transport=self._transport,
            )
        return self._client
