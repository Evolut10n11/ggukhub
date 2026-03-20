from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Mapping

from pydantic import BaseModel


class DialogStep(str, Enum):
    IDLE = "idle"
    AWAITING_JK = "awaiting_jk"
    AWAITING_HOUSE = "awaiting_house"
    AWAITING_ENTRANCE = "awaiting_entrance"
    AWAITING_APARTMENT = "awaiting_apartment"
    AWAITING_PHONE = "awaiting_phone"
    AWAITING_PROBLEM = "awaiting_problem"
    AWAITING_PHONE_REUSE_CONFIRM = "awaiting_phone_reuse_confirm"
    AWAITING_CATEGORY_CONFIRM = "awaiting_category_confirm"
    AWAITING_CATEGORY_SELECT = "awaiting_category_select"
    AWAITING_REPORT_CONFIRM = "awaiting_report_confirm"
    AWAITING_REPORT_CORRECTION = "awaiting_report_correction"


class ClassificationSource(str, Enum):
    RULES = "rules"
    MANUAL = "manual"


class DialogSessionData(BaseModel):
    jk: str | None = None
    house: str | None = None
    entrance: str | None = None
    apartment: str | None = None
    phone: str | None = None
    problem_text: str | None = None
    auto_category: str | None = None
    category: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DialogSessionData":
        return cls.model_validate(dict(value))

    def to_mapping(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


@dataclass(slots=True)
class DialogSnapshot:
    step: DialogStep
    data: DialogSessionData


@dataclass(slots=True)
class ClassificationResult:
    category: str
    source: ClassificationSource
    raw_output: str | None = None
    timed_out: bool = False
    fallback_used: bool = False
    metadata: dict[str, Any] | None = None


SendTextCallable = Callable[[str, Any | None], Awaitable[None]]
ClearKeyboardCallable = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class DialogTransport:
    telegram_id: int
    display_name: str | None
    send_text: SendTextCallable
    clear_inline_keyboard: ClearKeyboardCallable


@dataclass(slots=True)
class FinalizedReportDraft:
    jk: str | None
    house: str
    entrance: str | None
    apartment: str
    phone: str
    problem_text: str
    category: str
    address: str
    scope_key: str
