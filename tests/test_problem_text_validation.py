from __future__ import annotations

from app.telegram.dialog.problem_validation import (
    ProblemTextIssue,
    problem_text_rejection_message,
    validate_problem_text,
)


def test_validate_problem_text_accepts_clear_problem() -> None:
    result = validate_problem_text("Не работает лифт в подъезде")
    assert result.is_valid
    assert result.issue is None


def test_validate_problem_text_rejects_low_signal_input() -> None:
    result = validate_problem_text("1")
    assert not result.is_valid
    assert result.issue in {ProblemTextIssue.LOW_SIGNAL, ProblemTextIssue.TOO_SHORT}
    assert "Нужно коротко и по делу" in problem_text_rejection_message(result)


def test_validate_problem_text_rejects_abusive_input() -> None:
    result = validate_problem_text("Сука, опять лифт не работает")
    assert not result.is_valid
    assert result.issue == ProblemTextIssue.ABUSIVE
    assert "без оскорблений" in problem_text_rejection_message(result)
