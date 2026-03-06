from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import app.responders.llm_responder as llm_module
from app.config.settings import ALLOWED_LLM_MODEL, Settings
from app.responders.llm_responder import LLMResponder


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
    assert model_settings["max_tokens"] == 512

    run_kwargs = captured["run_kwargs"]
    assert "model" in run_kwargs
    assert "user_prompt" in run_kwargs
    assert "101" in str(run_kwargs["user_prompt"])


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
@pytest.mark.skipif(
    os.getenv("RUN_QWEN_LIVE_TESTS") != "1",
    reason="Set RUN_QWEN_LIVE_TESTS=1 to run real Qwen integration smoke",
)
async def test_qwen_live_smoke_report_created() -> None:
    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url=os.getenv("QWEN_TEST_BASE_URL", "http://192.168.130.159:8080/v1"),
        llm_api_key=os.getenv("QWEN_TEST_API_KEY", ""),
        llm_max_tokens=256,
    )
    responder = LLMResponder(settings)

    output = await responder.report_created(local_id=999, bitrix_id=None)
    assert isinstance(output, str)
    assert output.strip()
