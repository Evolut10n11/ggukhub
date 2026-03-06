from __future__ import annotations

from typing import Any

from app.bitrix.models import BitrixParsedEvent


def verify_bitrix_secret(payload: dict[str, Any], provided_secret: str | None, expected_secret: str | None) -> bool:
    if not expected_secret:
        return True

    candidates: list[str | None] = [
        provided_secret,
        payload.get("secret"),
        payload.get("token"),
    ]

    auth = payload.get("auth")
    if isinstance(auth, dict):
        candidates.append(auth.get("application_token"))

    for candidate in candidates:
        if candidate and candidate == expected_secret:
            return True
    return False


def _pick_str(*values: object) -> str | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            candidate = value.strip()
            if candidate:
                return candidate
        else:
            return str(value)
    return None


def parse_bitrix_event(payload: dict[str, Any]) -> BitrixParsedEvent:
    event_type = _pick_str(payload.get("event"), payload.get("type"), "generic") or "generic"

    data = payload.get("data")
    data_dict = data if isinstance(data, dict) else {}
    fields = data_dict.get("FIELDS")
    fields_dict = fields if isinstance(fields, dict) else {}

    bitrix_id = _pick_str(
        payload.get("bitrix_id"),
        payload.get("ID"),
        payload.get("id"),
        data_dict.get("ID"),
        data_dict.get("id"),
        fields_dict.get("ID"),
    )
    status = _pick_str(
        payload.get("status"),
        payload.get("status_id"),
        data_dict.get("STATUS_ID"),
        fields_dict.get("STATUS_ID"),
        fields_dict.get("STAGE_ID"),
    )
    message = _pick_str(
        payload.get("message"),
        payload.get("text"),
        data_dict.get("COMMENT"),
        fields_dict.get("COMMENT"),
    )

    return BitrixParsedEvent(event_type=event_type, bitrix_id=bitrix_id, status=status, message=message)

