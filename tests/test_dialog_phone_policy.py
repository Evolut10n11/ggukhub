from __future__ import annotations

from app.telegram.extractors import ExtractedReportContext
from app.telegram.handlers.dialog import _merge_extracted_context, _next_missing_step
from app.telegram.constants import STEP_AWAITING_PHONE


def test_merge_extracted_context_does_not_fill_phone_from_history() -> None:
    data = {"jk": "Pride Park", "house": "5", "entrance": "3", "apartment": "78"}
    extracted = ExtractedReportContext()

    _merge_extracted_context(data, extracted)

    assert "phone" not in data


def test_next_missing_step_requires_phone_when_not_in_payload() -> None:
    data = {
        "jk": "Pride Park",
        "house": "5",
        "entrance": "3",
        "apartment": "78",
        "problem_text": "Лифт не работает",
    }

    step = _next_missing_step(data, user_phone=None)
    assert step == STEP_AWAITING_PHONE

