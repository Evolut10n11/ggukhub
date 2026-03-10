from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.telegram.dialog.models import DialogSessionData, DialogStep
from app.telegram.dialog.state_machine import next_missing_step
from app.telegram.keyboards import build_jk_keyboard


@dataclass(slots=True)
class IdleFlowDecision:
    next_step: DialogStep
    prompt_text: str | None = None
    reply_markup: Any | None = None
    show_collected_fields: bool = False
    request_saved_phone_reuse: bool = False
    ready_for_confirmation: bool = False


def resolve_idle_flow(
    *,
    data: DialogSessionData,
    user_phone: str | None,
    housing_complexes: list[str],
) -> IdleFlowDecision:
    next_step = next_missing_step(data, user_phone)

    if next_step == DialogStep.AWAITING_JK:
        return IdleFlowDecision(
            next_step=next_step,
            prompt_text=(
                "Приняла обращение. Для заявки сначала выберите, пожалуйста, ваш ЖК ниже. "
                "Если не нашли его в списке, нажмите «Не вижу / не знаю свой ЖК»."
            ),
            reply_markup=build_jk_keyboard(housing_complexes, page=0),
        )
    if next_step == DialogStep.AWAITING_HOUSE:
        return IdleFlowDecision(next_step=next_step, prompt_text="Приняла обращение. Уточните, пожалуйста, дом.")
    if next_step == DialogStep.AWAITING_ENTRANCE:
        return IdleFlowDecision(next_step=next_step, prompt_text="Укажите подъезд. Если не знаете, напишите «-».")
    if next_step == DialogStep.AWAITING_APARTMENT:
        return IdleFlowDecision(next_step=next_step, prompt_text="Укажите номер квартиры.")
    if next_step == DialogStep.AWAITING_PHONE:
        return IdleFlowDecision(
            next_step=next_step,
            prompt_text="Укажите телефон для связи, например +7XXXXXXXXXX.",
        )
    if next_step == DialogStep.AWAITING_PROBLEM:
        return IdleFlowDecision(
            next_step=next_step,
            prompt_text="Опишите, пожалуйста, проблему в 1-2 предложениях.",
        )
    if next_step == DialogStep.AWAITING_PHONE_REUSE_CONFIRM:
        return IdleFlowDecision(next_step=next_step, request_saved_phone_reuse=True)
    return IdleFlowDecision(
        next_step=next_step,
        show_collected_fields=True,
        ready_for_confirmation=True,
    )
