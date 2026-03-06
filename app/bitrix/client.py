from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.core.models import Report, User


class BitrixClientError(RuntimeError):
    pass


class BitrixClient:
    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._settings.bitrix_enabled

    def _build_url(self, method: str) -> tuple[str, dict[str, str]]:
        if self._settings.bitrix_webhook_url:
            base = self._settings.bitrix_webhook_url.rstrip("/")
            return f"{base}/{method}.json", {}
        if self._settings.bitrix_rest_url and self._settings.bitrix_token:
            base = self._settings.bitrix_rest_url.rstrip("/")
            return f"{base}/{method}.json", {"Authorization": f"Bearer {self._settings.bitrix_token}"}
        raise BitrixClientError("Bitrix is not configured")

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise BitrixClientError("Bitrix integration is disabled")
        url, headers = self._build_url(method)
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        if "error" in data:
            raise BitrixClientError(str(data.get("error_description") or data["error"]))
        return data

    @staticmethod
    def _extract_result_id(data: dict[str, Any]) -> str:
        result = data.get("result")
        if isinstance(result, (int, str)):
            return str(result)
        if isinstance(result, dict):
            for key in ("ID", "id", "item", "result"):
                value = result.get(key)
                if value is not None:
                    return str(value)
        raise BitrixClientError("Cannot extract Bitrix id from response")

    async def create_ticket(self, report: Report, user: User) -> str:
        fields: dict[str, Any] = {
            self._settings.bitrix_field_title: f"Заявка УК #{report.id}",
            self._settings.bitrix_field_description: (
                f"{report.text}\n\n"
                f"Категория: {report.category}\n"
                f"ЖК: {report.jk or 'не указан'}\n"
                f"Адрес: {report.address}\n"
                f"Квартира: {report.apt}\n"
                f"Телефон: {report.phone}"
            ),
            self._settings.bitrix_field_jk: report.jk or "не указан",
            self._settings.bitrix_field_address: report.address,
            self._settings.bitrix_field_category: report.category,
            self._settings.bitrix_field_telegram_id: str(user.telegram_id),
            self._settings.bitrix_field_local_report_id: str(report.id),
        }

        if self._settings.bitrix_field_phone == "PHONE":
            fields["PHONE"] = [{"VALUE": report.phone, "VALUE_TYPE": "WORK"}]
        else:
            fields[self._settings.bitrix_field_phone] = report.phone

        data = await self._call(self._settings.bitrix_ticket_method, {"fields": fields})
        return self._extract_result_id(data)

    async def add_comment(self, bitrix_id: str, text: str) -> None:
        payload = {
            "fields": {
                "ENTITY_ID": int(bitrix_id) if bitrix_id.isdigit() else bitrix_id,
                "ENTITY_TYPE": self._settings.bitrix_entity_type,
                "COMMENT": text,
            }
        }
        _ = await self._call(self._settings.bitrix_comment_method, payload)

    async def update_status(self, bitrix_id: str, status: str) -> None:
        payload = {
            "id": int(bitrix_id) if bitrix_id.isdigit() else bitrix_id,
            "fields": {self._settings.bitrix_field_status: status},
        }
        _ = await self._call(self._settings.bitrix_update_method, payload)

