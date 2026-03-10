from __future__ import annotations

from abc import ABC, abstractmethod

from app.responders.models import GeneratedResponse


class BaseResponder(ABC):
    async def report_created(self, local_id: int, bitrix_id: str | None) -> str:
        return (await self.build_report_created(local_id, bitrix_id)).text

    @abstractmethod
    async def build_report_created(self, local_id: int, bitrix_id: str | None) -> GeneratedResponse:
        raise NotImplementedError
