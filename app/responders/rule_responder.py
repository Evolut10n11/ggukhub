from __future__ import annotations

from app.core.telemetry import start_flow_telemetry
from app.responders.models import GeneratedResponse


class RuleResponder:
    async def report_created(self, local_id: int, bitrix_id: str | None) -> str:
        return (await self.build_report_created(local_id, bitrix_id)).text

    async def build_report_created(self, local_id: int, bitrix_id: str | None) -> GeneratedResponse:
        telemetry = start_flow_telemetry("report_created", "response_generator")
        display_id = bitrix_id or str(local_id)
        chunks = [
            "Я зарегистрировала обращение и передала его диспетчеру.",
            f"Номер заявки: {display_id}.",
        ]
        chunks.append("Если понадобится, я напишу вам обновление по статусу.")
        return GeneratedResponse(
            text="\n".join(chunks),
            metadata=telemetry.finish(
                bitrix_id=bitrix_id,
                local_report_id=local_id,
            ),
        )
