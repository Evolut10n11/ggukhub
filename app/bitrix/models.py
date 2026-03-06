from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BitrixParsedEvent:
    event_type: str
    bitrix_id: str | None = None
    status: str | None = None
    message: str | None = None

