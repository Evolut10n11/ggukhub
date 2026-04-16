from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.bitrix.client import BitrixApiClient, BitrixClientError
from app.config import Settings
from app.core.storage import Storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConnectorMessage:
    """Parsed operator message from Bitrix Open Lines."""

    external_user_id: str
    text: str
    operator_name: str | None = None


class BitrixConnectorService:
    """Bitrix24 Open Lines connector (imconnector API).

    Sends client messages into an Open Line so that operators can reply
    from within Bitrix24 CRM. Operator replies arrive via a webhook
    (``POST /bitrix/connector``) and are forwarded back to the MAX chat.
    """

    def __init__(
        self,
        settings: Settings,
        client: BitrixApiClient,
        storage: Storage,
    ) -> None:
        self._settings = settings
        self._client = client
        self._storage = storage

    @property
    def enabled(self) -> bool:
        return self._settings.bitrix_connector_enabled and self._client.enabled

    @property
    def connector_id(self) -> str:
        return self._settings.bitrix_connector_id

    @property
    def line_id(self) -> int:
        return self._settings.bitrix_connector_line_id

    def external_user_id(self, max_user_id: int) -> str:
        return f"max_{max_user_id}"

    # ── Registration (one-time setup) ──

    async def register_connector(self, handler_url: str) -> dict[str, Any]:
        """Register the connector in Bitrix24 (call once during setup)."""
        payload = {
            "ID": self.connector_id,
            "NAME": "MAX Green Garden",
            "ICON": {},
            "PLACEMENT_HANDLER": handler_url,
        }
        try:
            return await self._client.call("imconnector.register", payload)
        except BitrixClientError as exc:
            logger.error("Failed to register connector: %s", exc)
            raise

    async def activate_connector(self) -> dict[str, Any]:
        """Activate the connector for the configured Open Line."""
        payload = {
            "CONNECTOR": self.connector_id,
            "LINE": self.line_id,
            "ACTIVE": 1,
        }
        try:
            return await self._client.call("imconnector.activate", payload)
        except BitrixClientError as exc:
            logger.error("Failed to activate connector: %s", exc)
            raise

    # ── Sending client messages to operator ──

    async def send_client_message(
        self,
        *,
        max_user_id: int,
        max_chat_id: int,
        user_name: str | None,
        phone: str | None,
        message: str,
        report_id: int | None = None,
        bitrix_id: str | None = None,
    ) -> bool:
        """Send a message from a MAX client into the Bitrix Open Line."""
        ext_id = self.external_user_id(max_user_id)

        user_info: dict[str, Any] = {"id": ext_id}
        if user_name:
            user_info["name"] = user_name
        if phone:
            user_info["phone"] = phone

        payload = {
            "CONNECTOR": self.connector_id,
            "LINE": self.line_id,
            "MESSAGES": [
                {
                    "user": user_info,
                    "message": {"text": message},
                }
            ],
        }

        try:
            await self._client.call("imconnector.send.messages", payload)
        except BitrixClientError as exc:
            logger.error("Failed to send connector message: %s", exc)
            return False

        existing = await self._storage.get_active_operator_chat_by_max_user(max_user_id)
        if existing is None:
            user = await self._storage.get_user_by_telegram_id(max_user_id)
            user_id = user.id if user else 0
            await self._storage.create_operator_chat(
                user_id=user_id,
                max_chat_id=max_chat_id,
                max_user_id=max_user_id,
                report_id=report_id,
                bitrix_id=bitrix_id,
            )

        return True

    # ── Parsing incoming operator messages ──

    def parse_operator_event(self, payload: dict[str, Any]) -> list[ConnectorMessage]:
        """Parse an incoming Bitrix Open Lines event into messages."""
        messages: list[ConnectorMessage] = []

        data = payload.get("data", payload)
        raw_messages = data.get("MESSAGES", data.get("messages", []))
        if not isinstance(raw_messages, list):
            return messages

        for msg in raw_messages:
            if not isinstance(msg, dict):
                continue

            chat_info = msg.get("chat", {})
            ext_user_id = str(chat_info.get("id", ""))
            if not ext_user_id:
                continue

            message_info = msg.get("message", {})
            text = str(message_info.get("text", "")).strip()
            if not text:
                continue

            operator_info = msg.get("user", msg.get("operator", {}))
            operator_name = operator_info.get("name") if isinstance(operator_info, dict) else None

            messages.append(ConnectorMessage(
                external_user_id=ext_user_id,
                text=text,
                operator_name=operator_name,
            ))

        return messages

    async def close_chat(self, max_user_id: int) -> None:
        """Close the active operator chat session for a MAX user."""
        chat = await self._storage.get_active_operator_chat_by_max_user(max_user_id)
        if chat:
            await self._storage.close_operator_chat(chat.id)
