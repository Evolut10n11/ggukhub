from __future__ import annotations

from app.telegram.constants import (
    STEP_AWAITING_ENTRANCE,
    STEP_AWAITING_HOUSE,
    STEP_AWAITING_PHONE,
    STEP_AWAITING_PROBLEM,
    STEP_AWAITING_PHONE_REUSE_CONFIRM,
    STEP_AWAITING_REPORT_CONFIRM,
)
from app.telegram.handlers.dialog import _next_missing_step


def test_next_missing_step_requires_house_after_jk() -> None:
    step = _next_missing_step({"jk": "Pride Park"}, user_phone=None)
    assert step == STEP_AWAITING_HOUSE


def test_next_missing_step_requires_entrance_when_absent() -> None:
    step = _next_missing_step({"jk": "Pride Park", "house": "5"}, user_phone=None)
    assert step == STEP_AWAITING_ENTRANCE


def test_next_missing_step_requires_phone_when_contacts_missing() -> None:
    payload = {
        "jk": "Pride Park",
        "house": "5",
        "entrance": "3",
        "apartment": "78",
        "problem_text": "Лифт не работает",
    }
    step = _next_missing_step(payload, user_phone=None)
    assert step == STEP_AWAITING_PHONE


def test_next_missing_step_prefers_problem_before_saved_phone_confirmation() -> None:
    payload = {
        "jk": "Pride Park",
        "house": "5",
        "entrance": "3",
        "apartment": "78",
    }
    step = _next_missing_step(payload, user_phone="+79990001122")
    assert step == STEP_AWAITING_PROBLEM


def test_next_missing_step_requests_saved_phone_confirmation_after_problem() -> None:
    payload = {
        "jk": "Pride Park",
        "house": "5",
        "entrance": "3",
        "apartment": "78",
        "problem_text": "Лифт не работает",
    }
    step = _next_missing_step(payload, user_phone="+79990001122")
    assert step == STEP_AWAITING_PHONE_REUSE_CONFIRM


def test_next_missing_step_ready_for_report_confirm() -> None:
    payload = {
        "jk": "Pride Park",
        "house": "5",
        "entrance": "3",
        "apartment": "78",
        "phone": "+79001112233",
        "problem_text": "Лифт не работает",
    }
    step = _next_missing_step(payload, user_phone=None)
    assert step == STEP_AWAITING_REPORT_CONFIRM
