from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class MaxApiError(RuntimeError):
    pass


class MaxBotClient:
    """Thin HTTP client for MAX Bot API (platform-api.max.ru)."""

    def __init__(self, settings: Settings) -> None:
        self._token = settings.max_bot_token
        self._base = settings.max_api_base_url.rstrip("/")
        # Read timeout must exceed long-polling timeout to avoid premature disconnect
        self._timeout = httpx.Timeout(10.0, read=settings.max_polling_timeout + 15)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base,
                headers={"Authorization": self._token},
                timeout=self._timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Core API calls ──

    async def get_me(self) -> dict[str, Any]:
        return await self._get("me")

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        attachments: list[dict[str, Any]] | None = None,
        format: str = "markdown",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"text": text, "format": format}
        if attachments:
            body["attachments"] = attachments
        return await self._post("messages", params={"chat_id": chat_id}, json=body)

    async def answer_callback(self, callback_id: str, *, notification: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"callback_id": callback_id}
        body: dict[str, Any] = {"notification": notification or ""}
        return await self._post("answers", params=params, json=body)

    async def get_updates(self, *, marker: int | None = None, timeout: int = 30) -> dict[str, Any]:
        params: dict[str, Any] = {"timeout": timeout}
        if marker is not None:
            params["marker"] = marker
        return await self._get("updates", params=params)

    async def edit_message(self, message_id: str, text: str, *, attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"text": text}
        if attachments:
            body["attachments"] = attachments
        return await self._put("messages", params={"message_id": message_id}, json=body)

    async def get_file_url(self, file_id: str) -> str | None:
        """Get download URL for a file attachment."""
        # MAX API doesn't have a direct file download endpoint like Telegram.
        # Files come with a 'url' field in the attachment payload.
        return None

    # ── HTTP helpers ──

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(f"/{path}", params=params)
        return self._handle_response(resp)

    async def _post(self, path: str, *, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.post(f"/{path}", params=params, json=json)
        return self._handle_response(resp)

    async def _put(self, path: str, *, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.put(f"/{path}", params=params, json=json)
        return self._handle_response(resp)

    @staticmethod
    def _handle_response(resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 429:
            raise MaxApiError("Rate limit exceeded")
        if resp.status_code >= 400:
            logger.error("MAX API error %s url=%s body=%s", resp.status_code, resp.url, resp.text[:500])
            raise MaxApiError(f"MAX API error {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if not data.get("success", True):
            raise MaxApiError(f"MAX API returned error: {data}")
        return data
