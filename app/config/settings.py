from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ALLOWED_LLM_MODEL = "Qwen3.5-35B-A3B"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )

    app_name: str = Field(default="Green Garden UK Assistant", alias="APP_NAME")
    base_url: str = Field(default="http://localhost:8000", alias="BASE_URL")
    database_url: str = Field(default="sqlite:///./app.db", alias="DATABASE_URL")

    telegram_bot_token: str = Field(
        default="",
        alias="TELEGRAM_BOT_TOKEN",
        validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN", "\ufeffTELEGRAM_BOT_TOKEN"),
    )
    telegram_use_webhook: bool = Field(default=False, alias="TELEGRAM_USE_WEBHOOK")
    telegram_webhook_secret: str | None = Field(default=None, alias="TELEGRAM_WEBHOOK_SECRET")

    bitrix_webhook_url: str | None = Field(default=None, alias="BITRIX_WEBHOOK_URL")
    bitrix_rest_url: str | None = Field(default=None, alias="BITRIX_REST_URL")
    bitrix_token: str | None = Field(default=None, alias="BITRIX_TOKEN")
    bitrix_shared_secret: str | None = Field(default=None, alias="BITRIX_SHARED_SECRET")

    bitrix_ticket_method: str = Field(default="crm.lead.add", alias="BITRIX_TICKET_METHOD")
    bitrix_comment_method: str = Field(default="crm.timeline.comment.add", alias="BITRIX_COMMENT_METHOD")
    bitrix_update_method: str = Field(default="crm.lead.update", alias="BITRIX_UPDATE_METHOD")
    bitrix_entity_type: str = Field(default="lead", alias="BITRIX_ENTITY_TYPE")
    bitrix_entity_type_id: int = Field(default=1, alias="BITRIX_ENTITY_TYPE_ID")

    bitrix_field_title: str = Field(default="TITLE", alias="BITRIX_FIELD_TITLE")
    bitrix_field_description: str = Field(default="COMMENTS", alias="BITRIX_FIELD_DESCRIPTION")
    bitrix_field_phone: str = Field(default="PHONE", alias="BITRIX_FIELD_PHONE")
    bitrix_field_jk: str = Field(default="UF_CRM_JK", alias="BITRIX_FIELD_JK")
    bitrix_field_address: str = Field(default="UF_CRM_ADDRESS", alias="BITRIX_FIELD_ADDRESS")
    bitrix_field_category: str = Field(default="UF_CRM_CATEGORY", alias="BITRIX_FIELD_CATEGORY")
    bitrix_field_telegram_id: str = Field(default="UF_CRM_TELEGRAM_ID", alias="BITRIX_FIELD_TELEGRAM_ID")
    bitrix_field_local_report_id: str = Field(default="UF_CRM_LOCAL_REPORT_ID", alias="BITRIX_FIELD_LOCAL_REPORT_ID")
    bitrix_field_status: str = Field(default="STATUS_ID", alias="BITRIX_FIELD_STATUS")

    use_llm: bool = Field(default=False, alias="USE_LLM")
    llm_base_url: str = Field(default="http://192.168.130.159:8080/v1", alias="LLM_BASE_URL")
    llm_model: str = Field(default=ALLOWED_LLM_MODEL, alias="LLM_MODEL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_max_tokens: int = Field(default=12288, alias="LLM_MAX_TOKENS")
    llm_few_shot_limit: int = Field(default=20, alias="LLM_FEW_SHOT_LIMIT")
    llm_category_max_tokens: int = Field(default=96, alias="LLM_CATEGORY_MAX_TOKENS")
    llm_category_timeout_seconds: float = Field(default=2.0, alias="LLM_CATEGORY_TIMEOUT_SECONDS")
    llm_category_soft_timeout_seconds: float = Field(default=1.0, alias="LLM_CATEGORY_SOFT_TIMEOUT_SECONDS")
    llm_responder_enabled: bool = Field(default=True, alias="LLM_RESPONDER_ENABLED")
    llm_report_max_tokens: int = Field(default=256, alias="LLM_REPORT_MAX_TOKENS")
    llm_report_timeout_seconds: float = Field(default=2.5, alias="LLM_REPORT_TIMEOUT_SECONDS")
    llm_report_soft_timeout_seconds: float = Field(default=1.2, alias="LLM_REPORT_SOFT_TIMEOUT_SECONDS")
    llm_report_failure_cooldown_seconds: float = Field(default=30.0, alias="LLM_REPORT_FAILURE_COOLDOWN_SECONDS")
    report_confirmation_budget_ms: int = Field(default=3500, alias="REPORT_CONFIRMATION_BUDGET_MS")
    bitrix_timeout_seconds: float = Field(default=10.0, alias="BITRIX_TIMEOUT_SECONDS")
    speech_enabled: bool = Field(default=False, alias="SPEECH_ENABLED")
    speech_base_url: str = Field(default="http://192.168.130.159:8080/v1", alias="SPEECH_BASE_URL")
    speech_api_key: str | None = Field(default=None, alias="SPEECH_API_KEY")
    speech_model: str = Field(default="whisper-1", alias="SPEECH_MODEL")
    speech_language: str = Field(default="ru", alias="SPEECH_LANGUAGE")
    speech_device: str = Field(default="cpu", alias="SPEECH_DEVICE")
    speech_compute_type: str = Field(default="int8", alias="SPEECH_COMPUTE_TYPE")
    speech_timeout_seconds: float = Field(default=45.0, alias="SPEECH_TIMEOUT_SECONDS")
    langfuse_host: str | None = Field(
        default=None,
        alias="LANGFUSE_HOST",
        validation_alias=AliasChoices("LANGFUSE_HOST", "LANGFUSE_BASE_URL"),
    )
    langfuse_public_key: str | None = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str | None = Field(default=None, alias="LANGFUSE_SECRET_KEY")
    langfuse_environment: str = Field(default="default", alias="LANGFUSE_ENVIRONMENT")
    langfuse_prompt_name: str | None = Field(default=None, alias="LANGFUSE_PROMPT_NAME")
    langfuse_prompt_label: str = Field(default="production", alias="LANGFUSE_PROMPT_LABEL")
    langfuse_prompt_cache_seconds: int = Field(default=300, alias="LANGFUSE_PROMPT_CACHE_SECONDS")

    incident_window_minutes: int = Field(default=15, alias="INCIDENT_WINDOW_MINUTES")
    incident_threshold: int = Field(default=5, alias="INCIDENT_THRESHOLD")

    categories_path: Path = Field(default=Path("data/categories.json"), alias="CATEGORIES_PATH")
    complexes_path: Path = Field(default=Path("data/housing_complexes.json"), alias="COMPLEXES_PATH")
    tariffs_path: Path = Field(default=Path("data/tariffs.json"), alias="TARIFFS_PATH")
    prompts_system_path: Path = Field(default=Path("app/prompts/system.txt"), alias="PROMPTS_SYSTEM_PATH")
    prompts_examples_path: Path = Field(default=Path("app/prompts/examples.json"), alias="PROMPTS_EXAMPLES_PATH")

    @field_validator("database_url")
    @classmethod
    def normalize_sqlite_url(cls, value: str) -> str:
        if value.startswith("sqlite:///"):
            return value.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return value

    @field_validator("llm_model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if value != ALLOWED_LLM_MODEL:
            raise ValueError(f"Allowed model is strictly: {ALLOWED_LLM_MODEL}")
        return value

    @field_validator("llm_max_tokens")
    @classmethod
    def validate_max_tokens(cls, value: int) -> int:
        if value < 256:
            raise ValueError("LLM_MAX_TOKENS must be >= 256")
        return value

    @field_validator("llm_few_shot_limit")
    @classmethod
    def validate_few_shot_limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError("LLM_FEW_SHOT_LIMIT must be >= 1")
        if value > 64:
            raise ValueError("LLM_FEW_SHOT_LIMIT must be <= 64")
        return value

    @field_validator("llm_category_max_tokens")
    @classmethod
    def validate_category_max_tokens(cls, value: int) -> int:
        if value < 32:
            raise ValueError("LLM_CATEGORY_MAX_TOKENS must be >= 32")
        return value

    @field_validator("llm_category_timeout_seconds")
    @classmethod
    def validate_category_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("LLM_CATEGORY_TIMEOUT_SECONDS must be > 0")
        return value

    @field_validator("llm_category_soft_timeout_seconds")
    @classmethod
    def validate_category_soft_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("LLM_CATEGORY_SOFT_TIMEOUT_SECONDS must be > 0")
        return value

    @field_validator("llm_report_max_tokens")
    @classmethod
    def validate_report_max_tokens(cls, value: int) -> int:
        if value < 64:
            raise ValueError("LLM_REPORT_MAX_TOKENS must be >= 64")
        return value

    @field_validator("llm_report_timeout_seconds")
    @classmethod
    def validate_report_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("LLM_REPORT_TIMEOUT_SECONDS must be > 0")
        return value

    @field_validator("llm_report_soft_timeout_seconds")
    @classmethod
    def validate_report_soft_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("LLM_REPORT_SOFT_TIMEOUT_SECONDS must be > 0")
        return value

    @field_validator("llm_report_failure_cooldown_seconds")
    @classmethod
    def validate_report_failure_cooldown(cls, value: float) -> float:
        if value < 0:
            raise ValueError("LLM_REPORT_FAILURE_COOLDOWN_SECONDS must be >= 0")
        return value

    @field_validator("report_confirmation_budget_ms")
    @classmethod
    def validate_report_confirmation_budget(cls, value: int) -> int:
        if value < 500:
            raise ValueError("REPORT_CONFIRMATION_BUDGET_MS must be >= 500")
        return value

    @field_validator("bitrix_timeout_seconds")
    @classmethod
    def validate_bitrix_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("BITRIX_TIMEOUT_SECONDS must be > 0")
        return value

    @field_validator("langfuse_prompt_cache_seconds")
    @classmethod
    def validate_prompt_cache_seconds(cls, value: int) -> int:
        if value < 0:
            raise ValueError("LANGFUSE_PROMPT_CACHE_SECONDS must be >= 0")
        return value

    @field_validator("speech_timeout_seconds")
    @classmethod
    def validate_speech_timeout(cls, value: float) -> float:
        if value < 5:
            raise ValueError("SPEECH_TIMEOUT_SECONDS must be >= 5")
        return value

    @property
    def bitrix_enabled(self) -> bool:
        return bool(self.bitrix_webhook_url or (self.bitrix_rest_url and self.bitrix_token))

    @property
    def langfuse_enabled(self) -> bool:
        if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("RUN_LANGFUSE_LIVE_TESTS") != "1":
            return False
        return bool(self.langfuse_host and self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
