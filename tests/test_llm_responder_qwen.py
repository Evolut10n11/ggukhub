from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import app.responders.llm_responder as llm_module
from app.config.settings import ALLOWED_LLM_MODEL, Settings
from app.responders.llm_responder import LLMResponder


class _DummyObservation:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []

    def __enter__(self) -> "_DummyObservation":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def update(self, **kwargs: object) -> None:
        self.updates.append(kwargs)


class _NestedObservation:
    def __init__(self, name: str = "root", registry: dict[str, list["_NestedObservation"]] | None = None) -> None:
        self.name = name
        self.updates: list[dict[str, object]] = []
        self.children: list[_NestedObservation] = []
        self.registry = registry if registry is not None else {}
        self.registry.setdefault(name, []).append(self)

    def __enter__(self) -> "_NestedObservation":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def update(self, **kwargs: object) -> None:
        self.updates.append(kwargs)

    def start_as_current_observation(self, **kwargs: object) -> "_NestedObservation":
        child = _NestedObservation(name=str(kwargs.get("name", "child")), registry=self.registry)
        self.children.append(child)
        return child

    def last_child(self, name: str) -> "_NestedObservation":
        return self.registry[name][-1]


@pytest.mark.asyncio
async def test_qwen_responder_uses_qwen_config_and_returns_llm_output(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_openai_model_from_config(config: object) -> object:
        captured["config"] = config
        return object()

    class DummyAgent:
        async def run(self, **kwargs: object) -> SimpleNamespace:
            captured["run_kwargs"] = kwargs
            return SimpleNamespace(output="ok from qwen path")

    monkeypatch.setattr(llm_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_module, "_writer_agent", DummyAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://127.0.0.1:8080/v1",
        llm_max_tokens=512,
        llm_api_key="",
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    responder = LLMResponder(settings)

    output = await responder.report_created(local_id=101, bitrix_id=None)
    assert output == "ok from qwen path"

    config = captured["config"]
    assert getattr(config, "model") == ALLOWED_LLM_MODEL
    assert getattr(config, "base_url") == "http://127.0.0.1:8080/v1"
    model_settings = getattr(config, "model_settings")
    assert model_settings["max_tokens"] == settings.llm_report_max_tokens

    run_kwargs = captured["run_kwargs"]
    assert "model" in run_kwargs
    assert "user_prompt" in run_kwargs
    assert "101" in str(run_kwargs["user_prompt"])


@pytest.mark.asyncio
async def test_qwen_responder_success_metadata_includes_prompt_source_and_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_openai_model_from_config(_: object) -> object:
        return object()

    class Usage:
        input_tokens = 14
        output_tokens = 6

    class DummyAgent:
        async def run(self, **kwargs: object) -> SimpleNamespace:
            _ = kwargs
            output = SimpleNamespace(output="ok from qwen path")
            output.usage = lambda: Usage()
            return output

    monkeypatch.setattr(llm_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_module, "_writer_agent", DummyAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://127.0.0.1:8080/v1",
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    responder = LLMResponder(settings)

    response = await responder.build_report_created(local_id=101, bitrix_id=None)

    assert response.source.value == "llm"
    assert response.metadata["prompt_source"] == "local_file"
    assert response.metadata["tokens_in"] == 14
    assert response.metadata["tokens_out"] == 6
    assert response.metadata["tokens_total"] == 20


@pytest.mark.asyncio
async def test_qwen_responder_falls_back_to_rules_when_agent_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_openai_model_from_config(_: object) -> object:
        return object()

    class FailingAgent:
        async def run(self, **_: object) -> SimpleNamespace:
            raise RuntimeError("qwen temporary failure")

    monkeypatch.setattr(llm_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_module, "_writer_agent", FailingAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://127.0.0.1:8080/v1",
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    responder = LLMResponder(settings)

    output = await responder.report_created(local_id=77, bitrix_id=None)
    assert "77" in output


@pytest.mark.asyncio
async def test_qwen_responder_falls_back_to_rules_when_agent_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_openai_model_from_config(_: object) -> object:
        return object()

    class SlowAgent:
        async def run(self, **_: object) -> SimpleNamespace:
            import asyncio

            await asyncio.sleep(0.05)
            return SimpleNamespace(output="late output")

    monkeypatch.setattr(llm_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_module, "_writer_agent", SlowAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://127.0.0.1:8080/v1",
        llm_report_timeout_seconds=0.01,
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    responder = LLMResponder(settings)

    output = await responder.report_created(local_id=78, bitrix_id=None)
    assert "78" in output


@pytest.mark.asyncio
async def test_qwen_responder_short_circuits_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_openai_model_from_config(_: object) -> object:
        return object()

    class SlowAgent:
        async def run(self, **_: object) -> SimpleNamespace:
            nonlocal calls
            calls += 1
            import asyncio

            await asyncio.sleep(0.05)
            return SimpleNamespace(output="late output")

    monkeypatch.setattr(llm_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_module, "_writer_agent", SlowAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://127.0.0.1:8080/v1",
        llm_report_timeout_seconds=0.01,
        llm_report_failure_cooldown_seconds=60.0,
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    responder = LLMResponder(settings)

    first_output = await responder.report_created(local_id=78, bitrix_id=None)
    second_output = await responder.report_created(local_id=79, bitrix_id=None)

    assert "78" in first_output
    assert "79" in second_output
    assert calls == 1


@pytest.mark.asyncio
async def test_qwen_responder_preserves_timeout_status_in_langfuse_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_openai_model_from_config(_: object) -> object:
        return object()

    class SlowAgent:
        async def run(self, **_: object) -> SimpleNamespace:
            import asyncio

            await asyncio.sleep(0.05)
            return SimpleNamespace(output="late output")

    monkeypatch.setattr(llm_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_module, "_writer_agent", SlowAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://127.0.0.1:8080/v1",
        llm_report_timeout_seconds=0.01,
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    responder = LLMResponder(settings)
    observation = _DummyObservation()
    monkeypatch.setattr(responder, "_start_flow_observation", lambda **_: observation)

    output = await responder.report_created(local_id=80, bitrix_id=None)

    assert "80" in output
    assert observation.updates
    last_update = observation.updates[-1]
    assert last_update["status_message"] == "writer_timeout_rule_fallback"
    assert "llm_unavailable_rule_fallback" not in {
        update.get("status_message") for update in observation.updates
    }
    assert last_update["level"] == "DEFAULT"
    assert last_update["metadata"]["fallback_reason"] == "timeout"
    assert last_update["metadata"]["budget_ms"] == 10


@pytest.mark.asyncio
async def test_qwen_responder_uses_soft_timeout_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_openai_model_from_config(_: object) -> object:
        return object()

    class SlowAgent:
        async def run(self, **_: object) -> SimpleNamespace:
            import asyncio

            await asyncio.sleep(0.05)
            return SimpleNamespace(output="late output")

    monkeypatch.setattr(llm_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_module, "_writer_agent", SlowAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://127.0.0.1:8080/v1",
        llm_report_timeout_seconds=2.5,
        llm_report_soft_timeout_seconds=0.01,
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    responder = LLMResponder(settings)

    response = await responder.build_report_created(local_id=81, bitrix_id=None)

    assert response.source.value == "rules"
    assert response.metadata["fallback_reason"] == "timeout"
    assert response.metadata["budget_ms"] == 10
    assert response.metadata["hard_timeout_ms"] == 2500


@pytest.mark.asyncio
async def test_qwen_responder_timeout_sets_parent_output_and_child_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_openai_model_from_config(_: object) -> object:
        return object()

    class SlowAgent:
        async def run(self, **_: object) -> SimpleNamespace:
            import asyncio

            await asyncio.sleep(0.05)
            return SimpleNamespace(output="late output")

    monkeypatch.setattr(llm_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_module, "_writer_agent", SlowAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://127.0.0.1:8080/v1",
        llm_report_timeout_seconds=0.01,
        llm_report_soft_timeout_seconds=0.01,
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    responder = LLMResponder(settings)
    responder._langfuse = object()
    root = _NestedObservation("response_generator run")
    monkeypatch.setattr(responder, "_start_flow_observation", lambda **_: root)

    response = await responder.build_report_created(local_id=82, bitrix_id=None)

    assert response.source.value == "rules"
    assert root.updates[-1]["output"] == response.text
    assert root.updates[-1]["metadata"]["fallback_reason"] == "timeout"
    writer_pipeline = root.last_child("writer_pipeline")
    assert writer_pipeline.updates[-1]["output"] == response.text
    assert writer_pipeline.updates[-1]["metadata"]["fallback_used"] is True
    generation = root.last_child(f"chat {ALLOWED_LLM_MODEL}")
    assert generation.updates[-1]["output"] == "[no model output: timeout; rule fallback used]"
    assert generation.updates[-1]["status_message"] == "writer_timeout_rule_fallback"
    assert generation.updates[-1]["metadata"]["timeout_occurred"] is True
    assert generation.updates[-1]["metadata"]["fallback_used"] is True
    assert generation.updates[-1]["metadata"]["fallback_source"] == "writer_pipeline"
    assert generation.updates[-1]["metadata"]["model_output_present"] is False


@pytest.mark.asyncio
async def test_qwen_responder_error_sets_parent_output_and_child_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_openai_model_from_config(_: object) -> object:
        return object()

    class FailingAgent:
        async def run(self, **_: object) -> SimpleNamespace:
            raise RuntimeError("qwen temporary failure")

    monkeypatch.setattr(llm_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_module, "_writer_agent", FailingAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://127.0.0.1:8080/v1",
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    responder = LLMResponder(settings)
    responder._langfuse = object()
    root = _NestedObservation("response_generator run")
    monkeypatch.setattr(responder, "_start_flow_observation", lambda **_: root)

    response = await responder.build_report_created(local_id=83, bitrix_id=None)

    assert response.source.value == "rules"
    assert root.updates[-1]["output"] == response.text
    assert root.updates[-1]["metadata"]["fallback_reason"] == "RuntimeError"
    generation = root.last_child(f"chat {ALLOWED_LLM_MODEL}")
    assert generation.updates[-1]["output"] == "[no model output: RuntimeError; rule fallback used]"
    assert generation.updates[-1]["status_message"] == "writer_failed_rule_fallback:RuntimeError"
    assert generation.updates[-1]["metadata"]["error_type"] == "RuntimeError"
    assert generation.updates[-1]["metadata"]["fallback_used"] is True


@pytest.mark.asyncio
async def test_qwen_responder_success_keeps_normal_child_and_parent_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_openai_model_from_config(_: object) -> object:
        return object()

    class DummyAgent:
        async def run(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(output="ok from qwen path")

    monkeypatch.setattr(llm_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_module, "_writer_agent", DummyAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://127.0.0.1:8080/v1",
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    responder = LLMResponder(settings)
    responder._langfuse = object()
    root = _NestedObservation("response_generator run")
    monkeypatch.setattr(responder, "_start_flow_observation", lambda **_: root)

    response = await responder.build_report_created(local_id=84, bitrix_id=None)

    assert response.text == "ok from qwen path"
    assert root.updates[-1]["output"] == "ok from qwen path"
    generation = root.last_child(f"chat {ALLOWED_LLM_MODEL}")
    assert generation.updates[-1]["output"] == "ok from qwen path"
    assert generation.updates[-1]["metadata"]["fallback_used"] is False
    assert generation.updates[-1]["metadata"]["model_output_present"] is True


@pytest.mark.asyncio
async def test_qwen_responder_invalid_output_uses_placeholder_and_rule_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_openai_model_from_config(_: object) -> object:
        return object()

    class DummyAgent:
        async def run(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(output="undefined")

    monkeypatch.setattr(llm_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_module, "_writer_agent", DummyAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://127.0.0.1:8080/v1",
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    responder = LLMResponder(settings)
    responder._langfuse = object()
    root = _NestedObservation("response_generator run")
    monkeypatch.setattr(responder, "_start_flow_observation", lambda **_: root)

    response = await responder.build_report_created(local_id=85, bitrix_id=None)

    assert response.source.value == "rules"
    assert root.updates[-1]["output"] == response.text
    assert root.updates[-1]["metadata"]["fallback_reason"] == "invalid_output"
    generation = root.last_child(f"chat {ALLOWED_LLM_MODEL}")
    assert generation.updates[-1]["output"] == "[no model output: invalid_output; rule fallback used]"
    assert generation.updates[-1]["status_message"] == "writer_invalid_output_rule_fallback"
    assert generation.updates[-1]["metadata"]["fallback_used"] is True


@pytest.mark.asyncio
async def test_qwen_responder_empty_output_uses_placeholder_and_rule_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_openai_model_from_config(_: object) -> object:
        return object()

    class DummyAgent:
        async def run(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(output="   ")

    monkeypatch.setattr(llm_module, "openai_model_from_config", fake_openai_model_from_config)
    monkeypatch.setattr(llm_module, "_writer_agent", DummyAgent())

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://127.0.0.1:8080/v1",
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    responder = LLMResponder(settings)
    responder._langfuse = object()
    root = _NestedObservation("response_generator run")
    monkeypatch.setattr(responder, "_start_flow_observation", lambda **_: root)

    response = await responder.build_report_created(local_id=86, bitrix_id=None)

    assert response.source.value == "rules"
    assert root.updates[-1]["output"] == response.text
    assert root.updates[-1]["metadata"]["fallback_reason"] == "empty_output"
    generation = root.last_child(f"chat {ALLOWED_LLM_MODEL}")
    assert generation.updates[-1]["output"] == "[no model output: empty_output; rule fallback used]"
    assert generation.updates[-1]["status_message"] == "writer_empty_output_rule_fallback"
    assert generation.updates[-1]["metadata"]["fallback_used"] is True


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_QWEN_LIVE_TESTS") != "1",
    reason="Set RUN_QWEN_LIVE_TESTS=1 to run real Qwen integration smoke",
)
async def test_qwen_live_smoke_report_created() -> None:
    llm_base_url = (os.getenv("QWEN_TEST_BASE_URL") or os.getenv("LLM_BASE_URL") or "").strip()
    if not llm_base_url:
        pytest.skip("QWEN_TEST_BASE_URL or LLM_BASE_URL is not configured")

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url=llm_base_url,
        llm_api_key=os.getenv("QWEN_TEST_API_KEY", ""),
        llm_max_tokens=256,
    )
    responder = LLMResponder(settings)

    output = await responder.report_created(local_id=999, bitrix_id=None)
    assert isinstance(output, str)
    assert output.strip()
