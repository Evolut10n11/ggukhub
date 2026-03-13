from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from langfuse import Langfuse

from app.config.settings import ALLOWED_LLM_MODEL, Settings
from app.responders.llm_responder import LLMResponder


@dataclass(frozen=True)
class Scenario:
    case_id: str
    local_id: int
    bitrix_id: str | None


SCENARIOS: list[Scenario] = [
    Scenario("no_bitrix_1", 92001, None),
    Scenario("no_bitrix_2", 92002, None),
    Scenario("bitrix_1", 92003, "B24-1001"),
    Scenario("bitrix_2", 92004, "B24-1002"),
    Scenario("bitrix_numeric", 92005, "220005"),
    Scenario("long_bitrix", 92006, "CRM-LEAD-92006"),
    Scenario("no_bitrix_3", 92007, None),
    Scenario("bitrix_3", 92008, "B24-1008"),
    Scenario("no_bitrix_4", 92009, None),
    Scenario("bitrix_4", 92010, "B24-1010"),
]


def _wait_for_trace(
    client: Langfuse,
    *,
    seen_ids: set[str],
    expected_local_id: int,
    timeout_seconds: int = 30,
) -> object:
    deadline = time.time() + timeout_seconds
    needle = f"Локальный номер: {expected_local_id}"
    while time.time() < deadline:
        traces = client.api.trace.list(limit=50).data
        for trace in traces:
            trace_id = str(getattr(trace, "id", ""))
            if not trace_id or trace_id in seen_ids:
                continue
            if str(getattr(trace, "name", "")) != "orchestrator_agent run":
                continue
            if needle not in str(getattr(trace, "input", "")):
                continue
            return trace
        time.sleep(1)

    raise AssertionError(f"No new orchestrator trace found for local_id={expected_local_id}")


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_LANGFUSE_LIVE_TESTS") != "1",
    reason="Set RUN_LANGFUSE_LIVE_TESTS=1 to run live Langfuse scenario suite",
)
async def test_langfuse_10_live_scenarios() -> None:
    llm_base_url = (os.getenv("QWEN_TEST_BASE_URL") or os.getenv("LLM_BASE_URL") or "").strip()
    if not llm_base_url:
        pytest.skip("QWEN_TEST_BASE_URL or LLM_BASE_URL is not configured")

    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url=llm_base_url,
        llm_api_key=os.getenv("QWEN_TEST_API_KEY", os.getenv("LLM_API_KEY", "")),
        llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "12288")),
        llm_few_shot_limit=int(os.getenv("LLM_FEW_SHOT_LIMIT", "20")),
    )
    if not settings.langfuse_enabled:
        pytest.skip("LANGFUSE_* is not configured")

    client = Langfuse(
        base_url=settings.langfuse_host,
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        environment=settings.langfuse_environment,
    )
    assert client.auth_check() is True

    responder = LLMResponder(settings)
    seen_ids = {trace.id for trace in client.api.trace.list(limit=100).data}
    created_ids: list[str] = []

    for scenario in SCENARIOS:
        output = await responder.report_created(local_id=scenario.local_id, bitrix_id=scenario.bitrix_id)
        assert output.strip(), f"empty output for {scenario.case_id}"
        assert str(scenario.local_id) in output, f"local_id missing in output for {scenario.case_id}"

        if responder._langfuse is not None:
            responder._langfuse.flush()

        trace = _wait_for_trace(
            client,
            seen_ids=seen_ids,
            expected_local_id=scenario.local_id,
        )
        trace_id = str(getattr(trace, "id"))
        seen_ids.add(trace_id)
        created_ids.append(trace_id)

        assert str(getattr(trace, "name", "")) == "orchestrator_agent run"
        assert str(scenario.local_id) in str(getattr(trace, "input", ""))
        assert str(getattr(trace, "output", "")).strip()

        observations = client.api.observations.get_many(trace_id=trace_id, limit=50).data
        names = {str(getattr(item, "name", "")) for item in observations}
        assert "running 1 tool" in names, f"missing chain node for {scenario.case_id}"
        assert "document_agent_tool" in names, f"missing tool node for {scenario.case_id}"
        assert "document_agent run" in names, f"missing agent node for {scenario.case_id}"
        assert any(name.startswith("chat ") for name in names), f"missing generation node for {scenario.case_id}"

    assert len(created_ids) == 10
    print(
        f"Langfuse scenario suite passed: {len(created_ids)} traces created "
        f"at {datetime.now(timezone.utc).isoformat()}"
    )
