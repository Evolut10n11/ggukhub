from __future__ import annotations

import os
import time

import pytest
from langfuse import Langfuse

from app.config.settings import ALLOWED_LLM_MODEL, Settings
from app.responders.llm_responder import LLMResponder


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_LANGFUSE_LIVE_TESTS") != "1",
    reason="Set RUN_LANGFUSE_LIVE_TESTS=1 to run live Langfuse smoke",
)
async def test_langfuse_live_trace_is_created() -> None:
    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url=os.getenv("QWEN_TEST_BASE_URL", os.getenv("LLM_BASE_URL", "http://192.168.130.159:8080/v1")),
        llm_api_key=os.getenv("QWEN_TEST_API_KEY", os.getenv("LLM_API_KEY", "")),
        llm_max_tokens=256,
    )
    if not settings.langfuse_enabled:
        pytest.skip("LANGFUSE_* is not configured")

    client = Langfuse(
        base_url=settings.langfuse_host,
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
    )
    assert client.auth_check() is True

    before_ids = {trace.id for trace in client.api.trace.list(limit=20).data}

    responder = LLMResponder(settings)
    output = await responder.report_created(local_id=9901, bitrix_id=None)
    assert output.strip()

    if responder._langfuse is not None:
        responder._langfuse.flush()
    time.sleep(2)

    after = client.api.trace.list(limit=20).data
    new_ids = [trace.id for trace in after if trace.id not in before_ids]
    assert new_ids, "No new Langfuse trace detected after LLM call"
