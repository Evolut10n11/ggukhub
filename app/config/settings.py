from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    database_url: str = Field(default="sqlite:///./var/app.db", alias="DATABASE_URL")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_log_level: str = Field(default="info", alias="API_LOG_LEVEL")

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
    bitrix_debug_webhook_url: str | None = Field(default=None, alias="BITRIX_DEBUG_WEBHOOK_URL")
    bitrix_request_override_url: str | None = Field(default=None, alias="BITRIX_REQUEST_OVERRIDE_URL")

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
    bitrix_field_apartment: str = Field(default="UF_CRM_APARTMENT", alias="BITRIX_FIELD_APARTMENT")
    bitrix_field_status: str = Field(default="STATUS_ID", alias="BITRIX_FIELD_STATUS")

    bitrix_deal_stage_id: str = Field(default="C1:NEW", alias="BITRIX_DEAL_STAGE_ID")
    bitrix_deal_assigned_by_id: str = Field(default="18388", alias="BITRIX_DEAL_ASSIGNED_BY_ID")
    bitrix_deal_category_id: str = Field(default="1", alias="BITRIX_DEAL_CATEGORY_ID")
    bitrix_lead_source_id: str = Field(
        default="49",
        alias="BITRIX_LEAD_SOURCE_ID",
        validation_alias=AliasChoices("BITRIX_LEAD_SOURCE_ID", "BITRIX_SOURCE_ID", "BITRIX_DEAL_SOURCE_ID"),
    )

    bitrix_timeout_seconds: float = Field(default=10.0, alias="BITRIX_TIMEOUT_SECONDS")
    bitrix_status_cache_ttl_seconds: int = Field(default=600, alias="BITRIX_STATUS_CACHE_TTL_SECONDS")
    bitrix_manager_user_ids: str = Field(default="", alias="BITRIX_MANAGER_USER_IDS")
    bitrix_urgent_notify_enabled: bool = Field(default=False, alias="BITRIX_URGENT_NOTIFY_ENABLED")
    bitrix_contact_linking_enabled: bool = Field(default=False, alias="BITRIX_CONTACT_LINKING_ENABLED")
    report_confirmation_budget_ms: int = Field(default=3500, alias="REPORT_CONFIRMATION_BUDGET_MS")

    speech_enabled: bool = Field(default=False, alias="SPEECH_ENABLED")
    speech_base_url: str = Field(default="", alias="SPEECH_BASE_URL")
    speech_api_key: str | None = Field(default=None, alias="SPEECH_API_KEY")
    speech_model: str = Field(default="whisper-1", alias="SPEECH_MODEL")
    speech_language: str = Field(default="ru", alias="SPEECH_LANGUAGE")
    speech_device: str = Field(default="cpu", alias="SPEECH_DEVICE")
    speech_compute_type: str = Field(default="int8", alias="SPEECH_COMPUTE_TYPE")
    speech_timeout_seconds: float = Field(default=45.0, alias="SPEECH_TIMEOUT_SECONDS")

    max_bot_token: str = Field(default="", alias="MAX_BOT_TOKEN")
    max_operator_bot_token: str = Field(default="", alias="MAX_OPERATOR_BOT_TOKEN")
    max_api_base_url: str = Field(default="https://platform-api.max.ru", alias="MAX_API_BASE_URL")
    max_polling_timeout: int = Field(default=30, alias="MAX_POLLING_TIMEOUT")
    max_operator_phones: str = Field(default="", alias="MAX_OPERATOR_PHONES")
    max_operator_user_ids: str = Field(default="", alias="MAX_OPERATOR_USER_IDS")

    # Bitrix24 Open Lines connector
    bitrix_connector_id: str = Field(default="max_green_garden", alias="BITRIX_CONNECTOR_ID")
    bitrix_connector_line_id: int = Field(default=1, alias="BITRIX_CONNECTOR_LINE_ID")
    bitrix_connector_enabled: bool = Field(default=False, alias="BITRIX_CONNECTOR_ENABLED")

    incident_window_minutes: int = Field(default=15, alias="INCIDENT_WINDOW_MINUTES")
    incident_threshold: int = Field(default=5, alias="INCIDENT_THRESHOLD")

    categories_path: Path = Field(default=Path("data/categories.json"), alias="CATEGORIES_PATH")
    complexes_path: Path = Field(default=Path("data/housing_complexes.json"), alias="COMPLEXES_PATH")
    tariffs_path: Path = Field(default=Path("data/tariffs.json"), alias="TARIFFS_PATH")

    @field_validator("database_url")
    @classmethod
    def normalize_sqlite_url(cls, value: str) -> str:
        if value.startswith("sqlite:///"):
            return value.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return value

    @field_validator("bitrix_timeout_seconds")
    @classmethod
    def validate_bitrix_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("BITRIX_TIMEOUT_SECONDS must be > 0")
        return value

    @field_validator("report_confirmation_budget_ms")
    @classmethod
    def validate_report_confirmation_budget(cls, value: int) -> int:
        if value < 500:
            raise ValueError("REPORT_CONFIRMATION_BUDGET_MS must be >= 500")
        return value

    @field_validator("speech_timeout_seconds")
    @classmethod
    def validate_speech_timeout(cls, value: float) -> float:
        if value < 5:
            raise ValueError("SPEECH_TIMEOUT_SECONDS must be >= 5")
        return value

    @property
    def max_enabled(self) -> bool:
        return bool(self.max_bot_token)

    @property
    def max_operator_bot_enabled(self) -> bool:
        return bool(self.max_operator_bot_token)

    @property
    def bitrix_enabled(self) -> bool:
        return bool(
            self.bitrix_request_override_url
            or self.bitrix_webhook_url
            or (self.bitrix_rest_url and self.bitrix_token)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
