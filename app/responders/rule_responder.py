from __future__ import annotations

from app.core.telemetry import start_flow_telemetry
from app.responders.base import BaseResponder
from app.responders.models import GeneratedResponse, ResponseGeneratorSource


class RuleResponder(BaseResponder):
    async def build_report_created(self, local_id: int, bitrix_id: str | None) -> GeneratedResponse:
        telemetry = start_flow_telemetry(
            "report_created",
            "response_generator",
            llm_enabled=False,
            responder_mode=ResponseGeneratorSource.RULES.value,
        )
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
            metadata=telemetry.finish(
                bitrix_id=bitrix_id,
                local_report_id=local_id,
                fallback_used=False,
                rule_vs_llm_path="rules",
                timeout_occurred=False,
            ),
        )
