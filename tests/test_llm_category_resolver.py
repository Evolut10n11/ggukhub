from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import app.core.llm_category as llm_category_module
from app.config.settings import ALLOWED_LLM_MODEL, Settings
from app.core.classifier import CategoryClassifier
from app.core.llm_category import LLMCategoryResolver


def _classifier() -> CategoryClassifier:
    rules = {
        "elevator": {"label": "Elevator", "keywords": ["elevator"]},
        "water_leak": {"label": "Water leak", "keywords": ["leak"]},
        "heating": {"label": "Heating", "keywords": ["cold"]},
        "other": {"label": "Other", "keywords": []},
    }
    return CategoryClassifier(rules)


def _settings(*, use_llm: bool = True) -> Settings:
    return Settings(
        telegram_bot_token="x",
        use_llm=use_llm,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://qwen.local/v1",
        llm_max_tokens=8192,
    )


@pytest.mark.asyncio
async def test_resolver_returns_code_from_agent_output(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_openai_model_from_config(config: object) -> object:
        captured["config"] = config
        return object()

    class DummyAgent:
        async def run(self, **kwargs: object) -> SimpleNamespace:
            captured["run_kwargs"] = kwargs
            return SimpleNamespace(output="elevator")

    monkeypatch.setattr(llm_category_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_category_module, "_category_agent", DummyAgent())

    resolver = LLMCategoryResolver(settings=_settings(), classifier=_classifier())
    category = await resolver.resolve("Lift is broken")

    assert category == "elevator"
    config = captured["config"]
    assert getattr(config, "model") == ALLOWED_LLM_MODEL
    assert getattr(config, "base_url") == "http://qwen.local/v1"
    model_settings = getattr(config, "model_settings")
    assert model_settings["max_tokens"] >= 512


@pytest.mark.asyncio
async def test_resolver_parses_json_style_output(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyAgent:
        async def run(self, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(output='{"category":"water_leak"}')

    monkeypatch.setattr(llm_category_module, "openai_model_from_config", lambda _: object())
    monkeypatch.setattr(llm_category_module, "_category_agent", DummyAgent())

    resolver = LLMCategoryResolver(settings=_settings(), classifier=_classifier())
    category = await resolver.resolve("Water dripping from ceiling")
    assert category == "water_leak"


@pytest.mark.asyncio
async def test_resolver_disabled_when_llm_off() -> None:
    resolver = LLMCategoryResolver(settings=_settings(use_llm=False), classifier=_classifier())
    assert resolver.enabled is False
    category = await resolver.resolve("anything")
    assert category is None


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_QWEN_LIVE_TESTS") != "1",
    reason="Set RUN_QWEN_LIVE_TESTS=1 to run real Qwen live category smoke",
)
async def test_resolver_live_qwen_typo_phrase() -> None:
    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url=os.getenv("QWEN_TEST_BASE_URL", "http://192.168.130.159:8080/v1"),
        llm_api_key=os.getenv("QWEN_TEST_API_KEY", ""),
        llm_max_tokens=8192,
    )
    resolver = LLMCategoryResolver(settings=settings, classifier=_classifier())
    category = await resolver.resolve("Ливт не работает, застряли на 5 этаже")

    assert category in {"elevator", "other"}
