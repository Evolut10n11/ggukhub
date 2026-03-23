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


# --- Feature 1: crm.lead.get ---


@dataclass(slots=True)
class BitrixLeadGetPayloadInput:
    bitrix_id: str
    select_fields: list[str]


@dataclass(slots=True)
class BitrixLeadInfo:
    bitrix_id: str
    status_id: str | None = None
    title: str | None = None
    date_modify: str | None = None


# --- Feature 2: crm.status.entity.items ---


@dataclass(slots=True)
class BitrixStatusItem:
    status_id: str
    name: str
    sort: int


# --- Feature 3: crm.timeline.comment.list ---


@dataclass(slots=True)
class BitrixTimelineComment:
    id: str
    comment: str
    created: str


# --- Feature 5: im.notify.system.add ---


@dataclass(slots=True)
class BitrixNotifyPayloadInput:
    user_id: int
    message: str


# --- Feature 6: crm.contact.add + crm.lead.contact.add ---


@dataclass(slots=True)
class BitrixContactPayloadInput:
    name: str
    phone: str
    telegram_id: str


@dataclass(slots=True)
class BitrixLeadContactLinkInput:
    lead_id: str
    contact_id: str
