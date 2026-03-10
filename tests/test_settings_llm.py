import pytest
from pydantic import ValidationError

from app.config.settings import ALLOWED_LLM_MODEL, Settings


def test_llm_max_tokens_allows_extended_value() -> None:
    settings = Settings(llm_max_tokens=12288, use_llm=False, telegram_bot_token="x")
    assert settings.llm_max_tokens == 12288


def test_llm_few_shot_limit_validation() -> None:
    settings = Settings(llm_few_shot_limit=20, use_llm=False, telegram_bot_token="x")
    assert settings.llm_few_shot_limit == 20

    with pytest.raises(ValidationError):
        _ = Settings(llm_few_shot_limit=0, use_llm=False, telegram_bot_token="x")


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


def test_llm_report_tuning_defaults_and_validation() -> None:
    settings = Settings(
        telegram_bot_token="x",
        use_llm=False,
        llm_category_max_tokens=96,
        llm_category_timeout_seconds=2.0,
        llm_report_max_tokens=256,
        llm_report_timeout_seconds=2.5,
        langfuse_prompt_cache_seconds=300,
    )
    assert settings.llm_category_max_tokens == 96
    assert settings.llm_category_timeout_seconds == 2.0
    assert settings.llm_report_max_tokens == 256
    assert settings.llm_report_timeout_seconds == 2.5
    assert settings.langfuse_prompt_cache_seconds == 300

    with pytest.raises(ValidationError):
        _ = Settings(telegram_bot_token="x", use_llm=False, llm_category_max_tokens=16)

    with pytest.raises(ValidationError):
        _ = Settings(telegram_bot_token="x", use_llm=False, llm_category_timeout_seconds=0)

    with pytest.raises(ValidationError):
        _ = Settings(telegram_bot_token="x", use_llm=False, llm_report_max_tokens=32)

    with pytest.raises(ValidationError):
        _ = Settings(telegram_bot_token="x", use_llm=False, llm_report_timeout_seconds=0)
