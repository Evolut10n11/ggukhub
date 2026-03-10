from __future__ import annotations

from app.telegram.dialog.models import DialogSessionData, DialogStep
from app.telegram.dialog.state_machine import next_missing_step


def test_next_missing_step_treats_missing_entrance_as_pending() -> None:
    data = DialogSessionData.model_validate(
        {
            "jk": "Pride Park",
            "house": "5",
        }
    )
    assert next_missing_step(data, user_phone=None) == DialogStep.AWAITING_ENTRANCE


def test_next_missing_step_allows_skipped_optional_entrance() -> None:
    data = DialogSessionData.model_validate(
        {
            "jk": "Pride Park",
            "house": "5",
            "entrance": None,
            "apartment": "78",
            "phone": "+79990001122",
            "problem_text": "Лифт не работает",
        }
    )
    assert next_missing_step(data, user_phone=None) == DialogStep.AWAITING_REPORT_CONFIRM
