from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langfuse import Langfuse
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.test import TestModel
from pydantic_ai_langfuse_extras.model import (
    AgentConfig,
    InstrumentedModel,
    add_langfuse_prompt_attributes,
    openai_model_from_config,
)
from pydantic_ai_langfuse_extras.prompt import convert_to_pydantic_messages

from app.config import Settings
from app.responders.base import BaseResponder
from app.responders.rule_responder import RuleResponder

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _WriterDeps:
    instructions: str
    few_shot_history: list[ModelMessage]
    writer_model: Any


_writer_agent = Agent(model=TestModel(), deps_type=_WriterDeps, name="uk_writer_agent", instrument=False)


@_writer_agent.instructions
async def _writer_instructions(ctx: RunContext[_WriterDeps]) -> str:
    return ctx.deps.instructions


class LLMResponder(BaseResponder):
    def __init__(self, settings: Settings):
        self._settings = settings
        self._fallback = RuleResponder()
        self._system = Path(settings.prompts_system_path).read_text(encoding="utf-8").strip()
        self._examples = json.loads(Path(settings.prompts_examples_path).read_text(encoding="utf-8"))
        self._housing_complexes = self._load_housing_complexes()
        self._category_codes = self._load_category_codes()
        self._domain_context = self._build_domain_context()
        self._few_shot_history = self._build_few_shot_history()

        self._langfuse: Langfuse | None = None
        self._langfuse_prompt_name = settings.langfuse_prompt_name
        self._langfuse_prompt_label = settings.langfuse_prompt_label
        self._cached_prompt_bundle: tuple[str, Any | None] | None = None
        self._cached_prompt_expires_at = 0.0
        self._cached_prompt_model_key: int | None = None
        self._cached_prompt_model: Any | None = None
        self._default_writer_model: Any | None = None

        if settings.langfuse_enabled:
            try:
                os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = settings.langfuse_environment
                self._langfuse = Langfuse(
                    base_url=settings.langfuse_host,
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    environment=settings.langfuse_environment,
                )
                if self._langfuse.auth_check():
                    # Keep pydantic-ai auto-instrumentation off to avoid noisy duplicate traces.
                    Agent.instrument_all(False)
                    logger.info("Langfuse tracing enabled for LLMResponder (manual nested trace)")
                else:
                    logger.warning("Langfuse auth check failed, running without prompt sync")
                    self._langfuse = None
            except Exception as error:
                logger.warning("Langfuse setup failed: %s", error)
                self._langfuse = None

        if not self._langfuse_prompt_name:
            self._default_writer_model = self._build_model(prompt=None)

    @staticmethod
    def _load_housing_complexes() -> list[str]:
        path = Path("data/housing_complexes.json")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return []

    @staticmethod
    def _load_category_codes() -> list[str]:
        path = Path("data/categories.json")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(raw, dict):
            return [str(key).strip() for key in raw.keys() if str(key).strip()]
        return []

    def _build_domain_context(self) -> str:
        categories_text = "\n".join(f"- {code}" for code in self._category_codes) or "- other"
        complexes_text = "\n".join(f"- {item}" for item in self._housing_complexes) or "- не указано"
        return (
            "Дополнительный контекст проекта:\n"
            "Категории обращений:\n"
            f"{categories_text}\n"
            "Справочник ЖК:\n"
            f"{complexes_text}\n"
            "Анти-примеры:\n"
            "- Не выдумывай сроки и причины.\n"
            "- Не давай контакты мастеров.\n"
            "- Не обещай выезд в конкретное время без подтверждения.\n"
        )

    def _build_few_shot_history(self) -> list[ModelMessage]:
        limit = min(len(self._examples), self._settings.llm_few_shot_limit)
        messages: list[dict[str, str]] = []
        for example in self._examples[:limit]:
            user = str(example.get("user", "")).strip()
            assistant = str(example.get("assistant", "")).strip()
            if user and assistant:
                messages.append({"role": "user", "content": user})
                messages.append({"role": "assistant", "content": assistant})
        return convert_to_pydantic_messages(messages)

    def _load_prompt_instructions(self) -> tuple[str, Any | None]:
        instructions = self._system
        prompt: Any | None = None
        if not self._langfuse or not self._langfuse_prompt_name:
            return instructions, prompt

        now = time.monotonic()
        if self._cached_prompt_bundle is not None and now < self._cached_prompt_expires_at:
            return self._cached_prompt_bundle

        if self._langfuse and self._langfuse_prompt_name:
            try:
                prompt = self._langfuse.get_prompt(
                    self._langfuse_prompt_name,
                    label=self._langfuse_prompt_label,
                )
                instructions = prompt.compile()
                self._cached_prompt_bundle = (instructions, prompt)
                self._cached_prompt_expires_at = now + self._settings.langfuse_prompt_cache_seconds
            except Exception as error:
                logger.warning("Failed to load prompt from Langfuse, fallback to local prompt: %s", error)
                if self._cached_prompt_bundle is not None:
                    return self._cached_prompt_bundle
                prompt = None
        return instructions, prompt

    def _build_report_prompt(self, local_id: int, bitrix_id: str | None) -> str:
        return (
            "Сформируй финальное подтверждение о регистрации заявки для жителя УК «Зелёный сад».\n"
            f"Локальный номер заявки: {local_id}.\n"
            f"Bitrix ID: {bitrix_id or 'нет'}.\n"
            "Тон: заботливая поддержка.\n"
            "Формат:\n"
            "- 2-4 короткие фразы;\n"
            "- номер заявки в первой фразе;\n"
            "- если есть Bitrix ID, упомяни отдельной фразой;\n"
            "- дай спокойный следующий шаг.\n"
            f"{self._domain_context}"
        )

    @staticmethod
    def _build_summary_input(local_id: int, bitrix_id: str | None) -> str:
        return (
            "Сформируй короткое подтверждение по заявке. "
            f"Локальный номер: {local_id}. "
            f"Bitrix ID: {bitrix_id or 'нет'}."
        )

    def _supports_prompt_attributes(self, model: Any) -> bool:
        supports = hasattr(model, "attributes") or hasattr(model, "_attributes")
        if isinstance(model, InstrumentedModel):
            supports = supports or hasattr(model.wrapped, "attributes") or hasattr(model.wrapped, "_attributes")
        return supports

    def _report_max_tokens(self) -> int:
        return max(64, min(self._settings.llm_max_tokens, self._settings.llm_report_max_tokens))

    def _build_model(self, prompt: Any | None) -> Any:
        config = AgentConfig(
            model=self._settings.llm_model,
            base_url=self._settings.llm_base_url,
            api_key=self._settings.llm_api_key or "local-no-key",
            model_settings={
                "max_tokens": self._report_max_tokens(),
                "temperature": 0.2,
            },
        )
        model = openai_model_from_config(config)
        if prompt is not None and self._supports_prompt_attributes(model):
            try:
                add_langfuse_prompt_attributes(model, prompt)
            except Exception as error:
                logger.warning("Failed to attach Langfuse prompt attributes: %s", error)
        return model

    def _start_flow_observation(self, *, summary_input: str, local_id: int, bitrix_id: str | None):
        if not self._langfuse:
            return nullcontext(None)
        return self._langfuse.start_as_current_observation(
            name="orchestrator_agent run",
            as_type="agent",
            input=summary_input,
            metadata={
                "component": "llm_responder",
                "flow": "report_created",
                "local_id": local_id,
                "bitrix_id": bitrix_id,
            },
        )

    def _start_generation_observation(self, *, parent_obs: Any | None, input_text: str, stage: str):
        params = dict(
            name=f"chat {self._settings.llm_model}",
            as_type="generation",
            input=input_text,
            model=self._settings.llm_model,
            model_parameters={
                "temperature": 0.2,
                "max_tokens": self._report_max_tokens(),
                "stage": stage,
            },
        )
        if parent_obs is not None and hasattr(parent_obs, "start_as_current_observation"):
            return parent_obs.start_as_current_observation(**params)
        if self._langfuse:
            return self._langfuse.start_as_current_observation(**params)
        return nullcontext(None)

    @staticmethod
    def _usage_details_from_result(result: Any) -> dict[str, int] | None:
        usage_fn = getattr(result, "usage", None)
        if not callable(usage_fn):
            return None
        usage = usage_fn()
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        return {
            "input": input_tokens,
            "output": output_tokens,
            "total": input_tokens + output_tokens,
        }

    async def _run_writer_pipeline(
        self,
        *,
        writer_deps: _WriterDeps,
        user_prompt: str,
        summary_input: str,
        few_shot_history: list[ModelMessage],
        flow_obs: Any | None,
    ) -> str:
        if not self._langfuse or flow_obs is None:
            result = await _writer_agent.run(
                user_prompt=user_prompt,
                deps=writer_deps,
                message_history=few_shot_history,
                model=writer_deps.writer_model,
            )
            return str(result.output).strip()

        with flow_obs.start_as_current_observation(
            name="running 1 tool",
            as_type="chain",
            input=summary_input,
        ) as chain_obs:
            with chain_obs.start_as_current_observation(
                name="document_agent_tool",
                as_type="tool",
                input=summary_input,
            ) as tool_obs:
                with tool_obs.start_as_current_observation(
                    name="document_agent run",
                    as_type="agent",
                    input=user_prompt,
                ) as writer_obs:
                    with self._start_generation_observation(
                        parent_obs=writer_obs,
                        input_text=user_prompt,
                        stage="document_agent",
                    ) as generation_obs:
                        result = await _writer_agent.run(
                            user_prompt=user_prompt,
                            deps=writer_deps,
                            message_history=few_shot_history,
                            model=writer_deps.writer_model,
                        )
                        output = str(result.output).strip()
                        usage_details = self._usage_details_from_result(result)
                        if generation_obs is not None:
                            generation_obs.update(output=output, usage_details=usage_details)

                    writer_obs.update(output=output)
                    tool_obs.update(output=output)
                    chain_obs.update(output=output)
                    return output

    async def report_created(self, local_id: int, bitrix_id: str | None) -> str:
        if not self._settings.use_llm:
            return await self._fallback.report_created(local_id, bitrix_id)

        instructions, prompt = self._load_prompt_instructions()
        few_shot_history = self._few_shot_history
        user_prompt = self._build_report_prompt(local_id, bitrix_id)
        summary_input = self._build_summary_input(local_id, bitrix_id)
        writer_model = self._resolve_writer_model(prompt)
        writer_deps = _WriterDeps(
            instructions=instructions,
            few_shot_history=few_shot_history,
            writer_model=writer_model,
        )

        with self._start_flow_observation(
            summary_input=summary_input,
            local_id=local_id,
            bitrix_id=bitrix_id,
        ) as flow_obs:
            try:
                output = await asyncio.wait_for(
                    self._run_writer_pipeline(
                        writer_deps=writer_deps,
                        user_prompt=user_prompt,
                        summary_input=summary_input,
                        few_shot_history=few_shot_history,
                        flow_obs=flow_obs,
                    ),
                    timeout=self._settings.llm_report_timeout_seconds,
                )
                if output:
                    if flow_obs is not None:
                        flow_obs.update(output=output, metadata={"mode": "writer_pipeline"})
                    return output
            except asyncio.TimeoutError:
                logger.warning("Writer pipeline timed out after %.2fs, fallback to rules", self._settings.llm_report_timeout_seconds)
                if flow_obs is not None:
                    flow_obs.update(level="WARNING", status_message="writer_timeout_rule_fallback")
            except Exception as error:
                logger.warning("Writer pipeline failed, fallback to rules: %s", error)
                if flow_obs is not None:
                    flow_obs.update(level="WARNING", status_message=f"writer_failed: {type(error).__name__}")

            fallback_output = await self._fallback.report_created(local_id, bitrix_id)
            if flow_obs is not None:
                flow_obs.update(
                    output=fallback_output,
                    level="WARNING",
                    status_message="llm_unavailable_rule_fallback",
                )
            return fallback_output

    def _resolve_writer_model(self, prompt: Any | None) -> Any:
        if prompt is None:
            if self._default_writer_model is None:
                self._default_writer_model = self._build_model(prompt=None)
            return self._default_writer_model

        model_key = id(prompt)
        if self._cached_prompt_model is not None and self._cached_prompt_model_key == model_key:
            return self._cached_prompt_model

        self._cached_prompt_model = self._build_model(prompt)
        self._cached_prompt_model_key = model_key
        return self._cached_prompt_model
