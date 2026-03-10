from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings


class BitrixClientError(RuntimeError):
    pass


class BitrixApiClient:
    def __init__(self, settings: Settings):
        self._settings = settings

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
        raise BitrixClientError("Bitrix is not configured")

    async def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise BitrixClientError("Bitrix integration is disabled")
        url, headers = self.build_url(method)
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        if "error" in data:
            raise BitrixClientError(str(data.get("error_description") or data["error"]))
        return data

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
        raise BitrixClientError("Cannot extract Bitrix id from response")
