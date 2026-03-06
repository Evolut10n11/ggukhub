from __future__ import annotations

from abc import ABC, abstractmethod


class BaseResponder(ABC):
    @abstractmethod
    async def report_created(self, local_id: int, bitrix_id: str | None) -> str:
        raise NotImplementedError

