from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class BitrixParsedEvent:
    event_type: str
    bitrix_id: str | None = None
    status: str | None = None
    message: str | None = None


@dataclass(slots=True)
class BitrixTicketPayloadInput:
    local_report_id: int
    telegram_id: int
    title: str
    description: str
    jk: str | None
    address: str
    category: str
    phone: str


@dataclass(slots=True)
class BitrixCommentPayloadInput:
    bitrix_id: str
    text: str
    entity_type: str


@dataclass(slots=True)
class BitrixStatusUpdatePayloadInput:
    bitrix_id: str
    status: str
    status_field: str


@dataclass(slots=True)
class BitrixWebhookResult:
    accepted: bool
    event_id: int
    event_type: str
    bitrix_id: str | None
    status: str | None
    telegram_notified: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
