from app.telegram.phrases import is_farewell_or_thanks, is_greeting


def test_greeting_phrase_detected() -> None:
    assert is_greeting("Здравствуйте, подскажите пожалуйста") is True


def test_farewell_or_thanks_detected() -> None:
    assert is_farewell_or_thanks("Спасибо большое!") is True


def test_neutral_phrase_not_detected() -> None:
    assert is_greeting("протекает вода") is False
    assert is_farewell_or_thanks("протекает вода") is False

