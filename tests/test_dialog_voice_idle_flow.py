from __future__ import annotations

from app.telegram.constants import STEP_AWAITING_JK, STEP_IDLE
from app.telegram.extractors import extract_report_context
from app.telegram.handlers.dialog import _is_unknown_jk


def test_idle_voice_without_jk_should_require_jk() -> None:
    data: dict[str, str] = {}
    extracted = extract_report_context("Лифт не работает, дом 5, подъезд 3, квартира 78", ["Pride Park"])
    if extracted.jk:
        data["jk"] = extracted.jk

    next_step = STEP_AWAITING_JK if _is_unknown_jk(data.get("jk")) else STEP_IDLE
    assert next_step == STEP_AWAITING_JK


def test_idle_voice_with_jk_should_not_require_jk() -> None:
    data: dict[str, str] = {}
    extracted = extract_report_context("Лифт не работает. ЖК Pride Park, дом 5, подъезд 3, квартира 78", ["Pride Park"])
    if extracted.jk:
        data["jk"] = extracted.jk

    next_step = STEP_AWAITING_JK if _is_unknown_jk(data.get("jk")) else STEP_IDLE
    assert next_step == STEP_IDLE

