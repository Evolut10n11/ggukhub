from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import app.core.llm_category as llm_category_module
from app.config.settings import ALLOWED_LLM_MODEL, Settings
from app.core.category_resolution import CategoryResolutionSource
from app.core.classifier import CategoryClassifier
from app.core.llm_category import LLMCategoryResolver


class _DummyObservation:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []

    def __enter__(self) -> "_DummyObservation":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def update(self, **kwargs: object) -> None:
        self.updates.append(kwargs)

    def start_as_current_observation(self, **_: object) -> "_DummyObservation":
        return self


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
    result = await resolver.resolve("Lift is broken")

    assert result.category == "elevator"
    assert result.source == CategoryResolutionSource.LLM
    assert result.raw_output == "elevator"
    assert result.fallback_used is False
    config = captured["config"]
    assert getattr(config, "model") == ALLOWED_LLM_MODEL
    assert getattr(config, "base_url") == "http://qwen.local/v1"
    model_settings = getattr(config, "model_settings")
    assert model_settings["max_tokens"] == 96
    assert result.metadata["flow_name"] == "category_resolution"
    assert result.metadata["step_name"] == "llm_resolver"
    assert result.metadata["budget_ms"] == 1000
    assert result.metadata["hard_timeout_ms"] == 2000


@pytest.mark.asyncio
async def test_resolver_parses_json_style_output(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyAgent:
        async def run(self, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(output='{"category":"water_leak"}')

    monkeypatch.setattr(llm_category_module, "openai_model_from_config", lambda _: object())
    monkeypatch.setattr(llm_category_module, "_category_agent", DummyAgent())

    resolver = LLMCategoryResolver(settings=_settings(), classifier=_classifier())
    result = await resolver.resolve("Water dripping from ceiling")
    assert result.category == "water_leak"
    assert result.raw_output == '{"category":"water_leak"}'


@pytest.mark.asyncio
async def test_resolver_metadata_includes_token_usage_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    class Usage:
        input_tokens = 11
        output_tokens = 3

    class DummyAgent:
        async def run(self, **kwargs: object) -> SimpleNamespace:
            output = SimpleNamespace(output="elevator")
            output.usage = lambda: Usage()
            return output

    monkeypatch.setattr(llm_category_module, "openai_model_from_config", lambda _: object())
    monkeypatch.setattr(llm_category_module, "_category_agent", DummyAgent())

    resolver = LLMCategoryResolver(settings=_settings(), classifier=_classifier())
    result = await resolver.resolve("Lift is broken")

    assert result.metadata["tokens_in"] == 11
    assert result.metadata["tokens_out"] == 3
    assert result.metadata["tokens_total"] == 14


@pytest.mark.asyncio
async def test_resolver_updates_langfuse_like_observation_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyAgent:
        async def run(self, **kwargs: object) -> SimpleNamespace:
            _ = kwargs
            return SimpleNamespace(output="elevator")

    monkeypatch.setattr(llm_category_module, "openai_model_from_config", lambda _: object())
    monkeypatch.setattr(llm_category_module, "_category_agent", DummyAgent())

    resolver = LLMCategoryResolver(settings=_settings(), classifier=_classifier())
    observation = _DummyObservation()
    monkeypatch.setattr(resolver, "_start_flow_observation", lambda **_: observation)
    monkeypatch.setattr(resolver, "_start_generation_observation", lambda **_: observation)

    result = await resolver.resolve("Lift is broken")

    assert result.category == "elevator"
    assert observation.updates
    assert any(update.get("output") == "elevator" for update in observation.updates)


@pytest.mark.asyncio
async def test_resolver_updates_langfuse_like_observation_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class SlowAgent:
        async def run(self, **kwargs: object) -> SimpleNamespace:
            _ = kwargs
            import asyncio

            await asyncio.sleep(0.05)
            return SimpleNamespace(output="elevator")

    monkeypatch.setattr(llm_category_module, "openai_model_from_config", lambda _: object())
    monkeypatch.setattr(llm_category_module, "_category_agent", SlowAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://qwen.local/v1",
        llm_max_tokens=8192,
        llm_category_timeout_seconds=0.01,
        llm_category_soft_timeout_seconds=0.01,
    )
    resolver = LLMCategoryResolver(settings=settings, classifier=_classifier())
    observation = _DummyObservation()
    monkeypatch.setattr(resolver, "_start_flow_observation", lambda **_: observation)
    monkeypatch.setattr(resolver, "_start_generation_observation", lambda **_: observation)

    result = await resolver.resolve("Lift is broken")

    assert result.category is None
    assert any(update.get("status_message") == "category_timeout_rule_fallback" for update in observation.updates)
    assert any(update.get("level") == "DEFAULT" for update in observation.updates)


@pytest.mark.asyncio
async def test_resolver_disabled_when_llm_off() -> None:
    resolver = LLMCategoryResolver(settings=_settings(use_llm=False), classifier=_classifier())
    assert resolver.enabled is False
    result = await resolver.resolve("anything")
    assert result.category is None
    assert result.fallback_used is True
    assert result.metadata["reason"] == "disabled"


@pytest.mark.asyncio
async def test_resolver_returns_none_when_agent_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_openai_model_from_config(_: object) -> object:
        return object()

    class SlowAgent:
        async def run(self, **kwargs: object) -> SimpleNamespace:
            _ = kwargs
            import asyncio

            await asyncio.sleep(0.05)
            return SimpleNamespace(output="elevator")

    monkeypatch.setattr(llm_category_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_category_module, "_category_agent", SlowAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://qwen.local/v1",
        llm_max_tokens=8192,
        llm_category_timeout_seconds=0.01,
        llm_category_soft_timeout_seconds=0.01,
    )
    resolver = LLMCategoryResolver(settings=settings, classifier=_classifier())

    result = await resolver.resolve("Lift is broken")
    assert result.category is None
    assert result.timed_out is True
    assert result.fallback_used is True
    assert result.metadata["reason"] == "timeout"


@pytest.mark.asyncio
async def test_resolver_uses_soft_timeout_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_openai_model_from_config(_: object) -> object:
        return object()

    class SlowAgent:
        async def run(self, **kwargs: object) -> SimpleNamespace:
            _ = kwargs
            import asyncio

            await asyncio.sleep(0.05)
            return SimpleNamespace(output="elevator")

    monkeypatch.setattr(llm_category_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_category_module, "_category_agent", SlowAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://qwen.local/v1",
        llm_max_tokens=8192,
        llm_category_timeout_seconds=2.0,
        llm_category_soft_timeout_seconds=0.01,
    )
    resolver = LLMCategoryResolver(settings=settings, classifier=_classifier())

    result = await resolver.resolve("Lift is broken")

    assert result.category is None
    assert result.timed_out is True
    assert result.metadata["budget_ms"] == 10
    assert result.metadata["hard_timeout_ms"] == 2000


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_QWEN_LIVE_TESTS") != "1",
    reason="Set RUN_QWEN_LIVE_TESTS=1 to run real Qwen live category smoke",
)
async def test_resolver_live_qwen_typo_phrase() -> None:
    llm_base_url = (os.getenv("QWEN_TEST_BASE_URL") or os.getenv("LLM_BASE_URL") or "").strip()
    if not llm_base_url:
        pytest.skip("QWEN_TEST_BASE_URL or LLM_BASE_URL is not configured")

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url=llm_base_url,
        llm_api_key=os.getenv("QWEN_TEST_API_KEY", ""),
        llm_max_tokens=8192,
    )
    resolver = LLMCategoryResolver(settings=settings, classifier=_classifier())
    result = await resolver.resolve("Ливт не работает, застряли на 5 этаже")

    assert result.category in {"elevator", "other", None}
