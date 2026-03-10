from __future__ import annotations

from app.config.settings import Settings
from app.responders.factory import create_responder
from app.responders.llm_responder import LLMResponder
from app.responders.rule_responder import RuleResponder


def test_factory_uses_llm_responder_by_default_when_llm_is_enabled() -> None:
    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_base_url="http://127.0.0.1:8080/v1",
    )

    responder = create_responder(settings)

    assert isinstance(responder, LLMResponder)


def test_factory_uses_rule_responder_when_explicitly_disabled() -> None:
    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_responder_enabled=False,
        llm_base_url="http://127.0.0.1:8080/v1",
    )

    responder = create_responder(settings)

    assert isinstance(responder, RuleResponder)
