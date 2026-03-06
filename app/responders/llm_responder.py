from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from langfuse import Langfuse
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.test import TestModel
from pydantic_ai_langfuse_extras.model import (
    AgentConfig,
    add_langfuse_prompt_attributes,
    openai_model_from_config,
)
from pydantic_ai_langfuse_extras.prompt import convert_to_pydantic_messages
from pydantic_ai_langfuse_extras.tracing import setup_otel_tracing

from app.config import Settings
from app.responders.base import BaseResponder
from app.responders.rule_responder import RuleResponder

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Deps:
    instructions: str


_agent = Agent(model=TestModel(), deps_type=_Deps)


@_agent.instructions
async def _instructions(ctx: RunContext[_Deps]) -> str:
    return ctx.deps.instructions


class LLMResponder(BaseResponder):
    def __init__(self, settings: Settings):
        self._settings = settings
        self._fallback = RuleResponder()
        self._system = Path(settings.prompts_system_path).read_text(encoding="utf-8").strip()
        self._examples = json.loads(Path(settings.prompts_examples_path).read_text(encoding="utf-8"))

        self._langfuse: Langfuse | None = None
        self._langfuse_prompt_name = settings.langfuse_prompt_name
        self._langfuse_prompt_label = settings.langfuse_prompt_label

        if settings.langfuse_enabled:
            try:
                tracer_provider = setup_otel_tracing()
                self._langfuse = Langfuse(tracer_provider=tracer_provider)
                if self._langfuse.auth_check():
                    Agent.instrument_all()
                    logger.info("Langfuse tracing enabled for LLMResponder")
                else:
                    logger.warning("Langfuse auth check failed, running without prompt sync")
                    self._langfuse = None
            except Exception as error:
                logger.warning("Langfuse setup failed: %s", error)
                self._langfuse = None

    def _build_few_shot_history(self) -> list[ModelMessage]:
        messages: list[dict[str, str]] = []
        for example in self._examples[:8]:
            user = str(example.get("user", "")).strip()
            assistant = str(example.get("assistant", "")).strip()
            if user and assistant:
                messages.append({"role": "user", "content": user})
                messages.append({"role": "assistant", "content": assistant})
        return convert_to_pydantic_messages(messages)

    async def report_created(self, local_id: int, bitrix_id: str | None) -> str:
        if not self._settings.use_llm:
            return await self._fallback.report_created(local_id, bitrix_id)

        instructions = self._system
        if self._langfuse and self._langfuse_prompt_name:
            try:
                prompt = self._langfuse.get_prompt(
                    self._langfuse_prompt_name,
                    label=self._langfuse_prompt_label,
                )
                instructions = prompt.compile()
            except Exception as error:
                logger.warning("Failed to load prompt from Langfuse, fallback to local prompt: %s", error)
                prompt = None
        else:
            prompt = None

        user_prompt = (
            "Сформируй короткое подтверждение по заявке. "
            f"Локальный номер: {local_id}. "
            f"Bitrix ID: {bitrix_id or 'нет'}. "
            "Тон: заботливая поддержка, не более 4 коротких фраз."
        )

        try:
            config = AgentConfig(
                model=self._settings.llm_model,
                base_url=self._settings.llm_base_url,
                api_key=self._settings.llm_api_key or "local-no-key",
                model_settings={
                    "max_tokens": self._settings.llm_max_tokens,
                    "temperature": 0.2,
                },
            )
            model = openai_model_from_config(config)
            if prompt is not None:
                add_langfuse_prompt_attributes(model, prompt)

            result = await _agent.run(
                user_prompt=user_prompt,
                deps=_Deps(instructions=instructions),
                message_history=self._build_few_shot_history(),
                model=model,
            )
            output = str(result.output).strip()
            if output:
                return output
        except Exception as error:
            logger.warning("LLM responder failed, fallback to rules: %s", error)

        return await self._fallback.report_created(local_id, bitrix_id)
