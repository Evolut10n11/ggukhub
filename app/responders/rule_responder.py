from __future__ import annotations

from app.responders.base import BaseResponder
from app.responders.models import GeneratedResponse, ResponseGeneratorSource


class RuleResponder(BaseResponder):
    async def build_report_created(self, local_id: int, bitrix_id: str | None) -> GeneratedResponse:
        chunks = [
            "Я зарегистрировала обращение и передала его диспетчеру.",
            f"Номер заявки: {local_id}.",
        ]
        if bitrix_id:
            chunks.append(f"Номер в Bitrix24: {bitrix_id}.")
        chunks.append("Если понадобится, я напишу вам обновление по статусу.")
        return GeneratedResponse(
            text="\n".join(chunks),
            source=ResponseGeneratorSource.RULES,
        )
