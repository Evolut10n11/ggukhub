import pytest
from pydantic import ValidationError

from app.config.settings import ALLOWED_LLM_MODEL, Settings


def test_llm_max_tokens_default_is_8192() -> None:
    settings = Settings(llm_max_tokens=8192, use_llm=False, telegram_bot_token="x")
    assert settings.llm_max_tokens == 8192


def test_llm_model_allows_only_qwen() -> None:
    settings = Settings(
        use_llm=True,
        telegram_bot_token="x",
        llm_model=ALLOWED_LLM_MODEL,
    )
    assert settings.llm_model == ALLOWED_LLM_MODEL

    with pytest.raises(ValidationError):
        _ = Settings(
            use_llm=True,
            telegram_bot_token="x",
            llm_model="gpt-4.1-mini",
        )
