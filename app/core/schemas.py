from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SessionPayload(BaseModel):
    step: str = "idle"
    data: dict[str, Any] = Field(default_factory=dict)


class ReportCreate(BaseModel):
    user_id: int
    jk: str | None
    address: str
    apt: str
    phone: str
    category: str
    text: str
    scope_key: str


class ReportAuditCreate(BaseModel):
    report_id: int
    stage: str
    regulation_version: str
    payload: dict[str, Any]


class ParsedBitrixEvent(BaseModel):
    event_type: str = "generic"
    bitrix_id: str | None = None
    status: str | None = None
    message: str | None = None
