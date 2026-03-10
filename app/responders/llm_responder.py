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
from app.core.telemetry import start_flow_telemetry
from app.responders.base import BaseResponder
from app.responders.models import GeneratedResponse, ResponseGeneratorSource
from app.responders.rule_responder import RuleResponder

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _WriterDeps:
    instructions: str
    few_shot_history: list[ModelMessage]
    writer_model: Any


@dataclass(slots=True)
class _WriterPipelineResult:
    output: str
    usage_details: dict[str, int] | None
    timed_out: bool = False
    error_type: str | None = None
    fallback_reason: str | None = None
    status_message: str | None = None
    fallback_text: str | None = None


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
        self._writer_cooldown_until = 0.0
        self._writer_cooldown_reason: str | None = None

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
                    logger.info("Langfuse auth check failed, running without prompt sync")
                    self._langfuse = None
            except Exception as error:
                logger.info("Langfuse setup failed: %s", error)
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

    def _effective_timeout_seconds(self) -> float:
        return min(
            self._settings.llm_report_timeout_seconds,
            self._settings.llm_report_soft_timeout_seconds,
        )

    @staticmethod
    def _normalize_model_output(value: Any) -> str:
        return str(value).strip()

    @staticmethod
    def _is_invalid_model_output(output: str) -> bool:
        return output.lower() in {"none", "null", "undefined", "[object object]"}

    def _build_observation_placeholder_output(
        self,
        *,
        fallback_reason: str,
        error_type: str | None = None,
    ) -> str:
        if fallback_reason == "timeout":
            detail = "timeout"
        elif fallback_reason == "empty_output":
            detail = "empty_output"
        elif fallback_reason == "invalid_output":
            detail = "invalid_output"
        elif fallback_reason == "error" and error_type:
            detail = error_type
        else:
            detail = error_type or fallback_reason
        return f"[no model output: {detail}; rule fallback used]"

    def _build_observation_metadata(
        self,
        *,
        step_name: str,
        effective_timeout: float,
        started_at: float,
        fallback_used: bool,
        timeout_occurred: bool,
        llm_attempted: bool,
        rule_vs_llm_path: str,
        prompt_source: str | None = None,
        fallback_reason: str | None = None,
        fallback_source: str | None = None,
        model_output_present: bool,
        usage_details: dict[str, int] | None = None,
        error_type: str | None = None,
    ) -> dict[str, Any]:
        budget_ms = int(effective_timeout * 1000)
        latency_ms = round((time.monotonic() - started_at) * 1000, 2)
        metadata: dict[str, Any] = {
            "flow_name": "report_created",
            "step_name": step_name,
            "latency_ms": latency_ms,
            "budget_ms": budget_ms,
            "budget_exceeded": latency_ms > budget_ms,
            "llm_enabled": True,
            "llm_attempted": llm_attempted,
            "model_name": self._settings.llm_model,
            "responder_mode": ResponseGeneratorSource.LLM.value,
            "fallback_used": fallback_used,
            "timeout_occurred": timeout_occurred,
            "rule_vs_llm_path": rule_vs_llm_path,
            "hard_timeout_ms": int(self._settings.llm_report_timeout_seconds * 1000),
            "model_output_present": model_output_present,
        }
        if fallback_reason is not None:
            metadata["fallback_reason"] = fallback_reason
        if fallback_source is not None:
            metadata["fallback_source"] = fallback_source
        if prompt_source is not None:
            metadata["prompt_source"] = prompt_source
        if error_type is not None:
            metadata["error_type"] = error_type
        if usage_details is not None:
            metadata["tokens_in"] = usage_details.get("input", 0)
            metadata["tokens_out"] = usage_details.get("output", 0)
            metadata["tokens_total"] = usage_details.get("total", 0)
        return metadata

    @staticmethod
    def _update_observation(
        observation: Any | None,
        *,
        output: str | None = None,
        status_message: str | None = None,
        metadata: dict[str, Any] | None = None,
        usage_details: dict[str, int] | None = None,
    ) -> None:
        if observation is None:
            return
        payload: dict[str, Any] = {"level": "DEFAULT"}
        if output is not None:
            payload["output"] = output
        if status_message is not None:
            payload["status_message"] = status_message
        if metadata is not None:
            payload["metadata"] = metadata
        if usage_details is not None:
            payload["usage_details"] = usage_details
        observation.update(**payload)

    def _update_writer_pipeline_success_observations(
        self,
        *,
        chain_obs: Any | None,
        tool_obs: Any | None,
        writer_obs: Any | None,
        generation_obs: Any | None,
        output: str,
        usage_details: dict[str, int] | None,
        effective_timeout: float,
        started_at: float,
        prompt_source: str | None,
    ) -> None:
        observations = (
            (chain_obs, "writer_pipeline"),
            (tool_obs, "confirmation_writer"),
            (writer_obs, "writer_agent"),
            (generation_obs, "model_generation"),
        )
        for observation, step_name in observations:
            metadata = self._build_observation_metadata(
                step_name=step_name,
                effective_timeout=effective_timeout,
                started_at=started_at,
                fallback_used=False,
                timeout_occurred=False,
                llm_attempted=True,
                rule_vs_llm_path="llm",
                prompt_source=prompt_source,
                model_output_present=True,
                usage_details=usage_details if step_name == "model_generation" else None,
            )
            self._update_observation(
                observation,
                output=output,
                metadata=metadata,
                usage_details=usage_details if step_name == "model_generation" else None,
            )

    def _update_writer_pipeline_fallback_observations(
        self,
        *,
        chain_obs: Any | None,
        tool_obs: Any | None,
        writer_obs: Any | None,
        generation_obs: Any | None,
        fallback_text: str,
        effective_timeout: float,
        started_at: float,
        status_message: str,
        fallback_reason: str,
        prompt_source: str | None,
        timeout_occurred: bool,
        error_type: str | None = None,
    ) -> None:
        placeholder_output = self._build_observation_placeholder_output(
            fallback_reason="error" if error_type else fallback_reason,
            error_type=error_type,
        )
        non_model_observations = (
            (chain_obs, "writer_pipeline"),
            (tool_obs, "confirmation_writer"),
            (writer_obs, "writer_agent"),
        )
        for observation, step_name in non_model_observations:
            metadata = self._build_observation_metadata(
                step_name=step_name,
                effective_timeout=effective_timeout,
                started_at=started_at,
                fallback_used=True,
                timeout_occurred=timeout_occurred,
                llm_attempted=True,
                rule_vs_llm_path="llm_fallback",
                prompt_source=prompt_source,
                fallback_reason=fallback_reason,
                fallback_source="writer_pipeline",
                model_output_present=False,
                error_type=error_type,
            )
            self._update_observation(
                observation,
                output=fallback_text,
                status_message=status_message,
                metadata=metadata,
            )

        generation_metadata = self._build_observation_metadata(
            step_name="model_generation",
            effective_timeout=effective_timeout,
            started_at=started_at,
            fallback_used=True,
            timeout_occurred=timeout_occurred,
            llm_attempted=True,
            rule_vs_llm_path="llm_fallback",
            prompt_source=prompt_source,
            fallback_reason=fallback_reason,
            fallback_source="writer_pipeline",
            model_output_present=False,
            error_type=error_type,
        )
        self._update_observation(
            generation_obs,
            output=placeholder_output,
            status_message=status_message,
            metadata=generation_metadata,
        )

    def _load_prompt_instructions(self) -> tuple[str, Any | None, str]:
        instructions = self._system
        prompt: Any | None = None
        if not self._langfuse or not self._langfuse_prompt_name:
            return instructions, prompt, "local_file"

        now = time.monotonic()
        if self._cached_prompt_bundle is not None and now < self._cached_prompt_expires_at:
            cached_instructions, cached_prompt = self._cached_prompt_bundle
            return cached_instructions, cached_prompt, "langfuse_cache"

        if self._langfuse and self._langfuse_prompt_name:
            try:
                prompt = self._langfuse.get_prompt(
                    self._langfuse_prompt_name,
                    label=self._langfuse_prompt_label,
                )
                instructions = prompt.compile()
                self._cached_prompt_bundle = (instructions, prompt)
                self._cached_prompt_expires_at = now + self._settings.langfuse_prompt_cache_seconds
                return instructions, prompt, "langfuse_live"
            except Exception as error:
                logger.info("Failed to load prompt from Langfuse, fallback to local prompt: %s", error)
                if self._cached_prompt_bundle is not None:
                    cached_instructions, cached_prompt = self._cached_prompt_bundle
                    return cached_instructions, cached_prompt, "langfuse_cache_fallback"
                prompt = None
        return instructions, prompt, "local_file_fallback"

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
                logger.info("Failed to attach Langfuse prompt attributes: %s", error)
        return model

    def _writer_cooldown_active(self) -> bool:
        return time.monotonic() < self._writer_cooldown_until

    def _start_writer_cooldown(self, reason: str) -> None:
        cooldown_seconds = self._settings.llm_report_failure_cooldown_seconds
        if cooldown_seconds <= 0:
            return
        self._writer_cooldown_until = time.monotonic() + cooldown_seconds
        self._writer_cooldown_reason = reason

    def _writer_cooldown_metadata(self) -> dict[str, Any]:
        remaining_seconds = max(0.0, self._writer_cooldown_until - time.monotonic())
        metadata: dict[str, Any] = {
            "mode": "rule_fallback",
            "fallback_source": "writer_cooldown",
            "cooldown_remaining_seconds": round(remaining_seconds, 2),
        }
        if self._writer_cooldown_reason:
            metadata["fallback_reason"] = self._writer_cooldown_reason
        return metadata

    def _start_flow_observation(self, *, summary_input: str, local_id: int, bitrix_id: str | None):
        if not self._langfuse:
            return nullcontext(None)
        effective_timeout = self._effective_timeout_seconds()
        return self._langfuse.start_as_current_observation(
            name="response_generator run",
            as_type="agent",
            input=summary_input,
            level="DEFAULT",
            metadata={
                "component": "llm_responder",
                "flow": "report_created",
                "local_id": local_id,
                "bitrix_id": bitrix_id,
                "budget_ms": int(effective_timeout * 1000),
                "hard_timeout_ms": int(self._settings.llm_report_timeout_seconds * 1000),
            },
        )

    def _start_generation_observation(self, *, parent_obs: Any | None, input_text: str, stage: str):
        params = dict(
            name=f"chat {self._settings.llm_model}",
            as_type="generation",
            input=input_text,
            level="DEFAULT",
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
        effective_timeout: float,
        prompt_source: str | None,
        fallback_text: str,
    ) -> _WriterPipelineResult:
        started_at = time.monotonic()
        if not self._langfuse or flow_obs is None:
            try:
                result = await asyncio.wait_for(
                    _writer_agent.run(
                        user_prompt=user_prompt,
                        deps=writer_deps,
                        message_history=few_shot_history,
                        model=writer_deps.writer_model,
                    ),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                return _WriterPipelineResult(
                    output="",
                    usage_details=None,
                    timed_out=True,
                    fallback_reason="timeout",
                    status_message="writer_timeout_rule_fallback",
                    fallback_text=fallback_text,
                )
            except Exception as error:
                return _WriterPipelineResult(
                    output="",
                    usage_details=None,
                    error_type=type(error).__name__,
                    fallback_reason=type(error).__name__,
                    status_message=f"writer_failed_rule_fallback:{type(error).__name__}",
                    fallback_text=fallback_text,
                )
            output = self._normalize_model_output(result.output)
            if not output:
                return _WriterPipelineResult(
                    output="",
                    usage_details=self._usage_details_from_result(result),
                    fallback_reason="empty_output",
                    status_message="writer_empty_output_rule_fallback",
                    fallback_text=fallback_text,
                )
            if self._is_invalid_model_output(output):
                return _WriterPipelineResult(
                    output="",
                    usage_details=self._usage_details_from_result(result),
                    fallback_reason="invalid_output",
                    status_message="writer_invalid_output_rule_fallback",
                    fallback_text=fallback_text,
                )
            return _WriterPipelineResult(
                output=output,
                usage_details=self._usage_details_from_result(result),
            )

        with flow_obs.start_as_current_observation(
            name="writer_pipeline",
            as_type="chain",
            input=summary_input,
            level="DEFAULT",
        ) as chain_obs:
            with chain_obs.start_as_current_observation(
                name="confirmation_writer",
                as_type="tool",
                input=summary_input,
                level="DEFAULT",
            ) as tool_obs:
                with tool_obs.start_as_current_observation(
                    name="writer_agent run",
                    as_type="agent",
                    input=user_prompt,
                    level="DEFAULT",
                ) as writer_obs:
                    with self._start_generation_observation(
                        parent_obs=writer_obs,
                        input_text=user_prompt,
                        stage="document_agent",
                    ) as generation_obs:
                        try:
                            result = await asyncio.wait_for(
                                _writer_agent.run(
                                    user_prompt=user_prompt,
                                    deps=writer_deps,
                                    message_history=few_shot_history,
                                    model=writer_deps.writer_model,
                                ),
                                timeout=effective_timeout,
                            )
                        except asyncio.TimeoutError:
                            self._update_writer_pipeline_fallback_observations(
                                chain_obs=chain_obs,
                                tool_obs=tool_obs,
                                writer_obs=writer_obs,
                                generation_obs=generation_obs,
                                fallback_text=fallback_text,
                                effective_timeout=effective_timeout,
                                started_at=started_at,
                                status_message="writer_timeout_rule_fallback",
                                fallback_reason="timeout",
                                prompt_source=prompt_source,
                                timeout_occurred=True,
                            )
                            return _WriterPipelineResult(
                                output="",
                                usage_details=None,
                                timed_out=True,
                                fallback_reason="timeout",
                                status_message="writer_timeout_rule_fallback",
                                fallback_text=fallback_text,
                            )
                        except Exception as error:
                            status_message = f"writer_failed_rule_fallback:{type(error).__name__}"
                            self._update_writer_pipeline_fallback_observations(
                                chain_obs=chain_obs,
                                tool_obs=tool_obs,
                                writer_obs=writer_obs,
                                generation_obs=generation_obs,
                                fallback_text=fallback_text,
                                effective_timeout=effective_timeout,
                                started_at=started_at,
                                status_message=status_message,
                                fallback_reason=type(error).__name__,
                                prompt_source=prompt_source,
                                timeout_occurred=False,
                                error_type=type(error).__name__,
                            )
                            return _WriterPipelineResult(
                                output="",
                                usage_details=None,
                                error_type=type(error).__name__,
                                fallback_reason=type(error).__name__,
                                status_message=status_message,
                                fallback_text=fallback_text,
                            )

                        output = self._normalize_model_output(result.output)
                        usage_details = self._usage_details_from_result(result)
                        if not output:
                            self._update_writer_pipeline_fallback_observations(
                                chain_obs=chain_obs,
                                tool_obs=tool_obs,
                                writer_obs=writer_obs,
                                generation_obs=generation_obs,
                                fallback_text=fallback_text,
                                effective_timeout=effective_timeout,
                                started_at=started_at,
                                status_message="writer_empty_output_rule_fallback",
                                fallback_reason="empty_output",
                                prompt_source=prompt_source,
                                timeout_occurred=False,
                            )
                            return _WriterPipelineResult(
                                output="",
                                usage_details=usage_details,
                                fallback_reason="empty_output",
                                status_message="writer_empty_output_rule_fallback",
                                fallback_text=fallback_text,
                            )
                        if self._is_invalid_model_output(output):
                            self._update_writer_pipeline_fallback_observations(
                                chain_obs=chain_obs,
                                tool_obs=tool_obs,
                                writer_obs=writer_obs,
                                generation_obs=generation_obs,
                                fallback_text=fallback_text,
                                effective_timeout=effective_timeout,
                                started_at=started_at,
                                status_message="writer_invalid_output_rule_fallback",
                                fallback_reason="invalid_output",
                                prompt_source=prompt_source,
                                timeout_occurred=False,
                            )
                            return _WriterPipelineResult(
                                output="",
                                usage_details=usage_details,
                                fallback_reason="invalid_output",
                                status_message="writer_invalid_output_rule_fallback",
                                fallback_text=fallback_text,
                            )

                    self._update_writer_pipeline_success_observations(
                        chain_obs=chain_obs,
                        tool_obs=tool_obs,
                        writer_obs=writer_obs,
                        generation_obs=generation_obs,
                        output=output,
                        usage_details=usage_details,
                        effective_timeout=effective_timeout,
                        started_at=started_at,
                        prompt_source=prompt_source,
                    )
                    return _WriterPipelineResult(output=output, usage_details=usage_details)

    async def build_report_created(self, local_id: int, bitrix_id: str | None) -> GeneratedResponse:
        if not self._settings.use_llm:
            return await self._fallback.build_report_created(local_id, bitrix_id)

        summary_input = self._build_summary_input(local_id, bitrix_id)
        effective_timeout = self._effective_timeout_seconds()
        telemetry = start_flow_telemetry(
            "report_created",
            "response_generator",
            budget_ms=int(effective_timeout * 1000),
            llm_enabled=True,
            responder_mode=ResponseGeneratorSource.LLM.value,
            model_name=self._settings.llm_model,
            hard_timeout_ms=int(self._settings.llm_report_timeout_seconds * 1000),
        )

        with self._start_flow_observation(
            summary_input=summary_input,
            local_id=local_id,
            bitrix_id=bitrix_id,
        ) as flow_obs:
            if self._writer_cooldown_active():
                fallback = await self._fallback.build_report_created(local_id, bitrix_id)
                metadata = telemetry.finish(
                    fallback_used=True,
                    rule_vs_llm_path="writer_short_circuit",
                    timeout_occurred=False,
                    llm_attempted=False,
                    **self._writer_cooldown_metadata(),
                )
                if flow_obs is not None:
                    flow_obs.update(
                        output=fallback.text,
                        level="DEFAULT",
                        status_message="writer_short_circuit_rule_fallback",
                        metadata=metadata,
                    )
                return GeneratedResponse(
                    text=fallback.text,
                    source=ResponseGeneratorSource.RULES,
                    fallback_used=True,
                    metadata=metadata,
                )

            instructions, prompt, prompt_source = self._load_prompt_instructions()
            few_shot_history = self._few_shot_history
            user_prompt = self._build_report_prompt(local_id, bitrix_id)
            writer_model = self._resolve_writer_model(prompt)
            writer_deps = _WriterDeps(
                instructions=instructions,
                few_shot_history=few_shot_history,
                writer_model=writer_model,
            )
            fallback = await self._fallback.build_report_created(local_id, bitrix_id)

            fallback_status_message = "writer_empty_output_rule_fallback"
            fallback_metadata: dict[str, Any] = {
                "mode": "rule_fallback",
                "fallback_source": "writer_pipeline",
                "fallback_reason": "empty_output",
            }
            result = await self._run_writer_pipeline(
                writer_deps=writer_deps,
                user_prompt=user_prompt,
                summary_input=summary_input,
                few_shot_history=few_shot_history,
                flow_obs=flow_obs,
                effective_timeout=effective_timeout,
                prompt_source=prompt_source,
                fallback_text=fallback.text,
            )
            if result.output:
                metadata = telemetry.finish(
                    fallback_used=False,
                    rule_vs_llm_path="llm",
                    timeout_occurred=False,
                    llm_attempted=True,
                    mode="writer_pipeline",
                    prompt_source=prompt_source,
                    tokens_in=result.usage_details.get("input") if result.usage_details else 0,
                    tokens_out=result.usage_details.get("output") if result.usage_details else 0,
                    tokens_total=result.usage_details.get("total") if result.usage_details else 0,
                )
                if flow_obs is not None:
                    flow_obs.update(output=result.output, level="DEFAULT", metadata=metadata)
                return GeneratedResponse(
                    text=result.output,
                    source=ResponseGeneratorSource.LLM,
                    fallback_used=False,
                    metadata=metadata,
                )
            if result.timed_out:
                logger.info("Writer pipeline timed out after %.2fs, fallback to rules", effective_timeout)
                fallback_status_message = "writer_timeout_rule_fallback"
                fallback_metadata = {
                    "mode": "rule_fallback",
                    "fallback_source": "writer_pipeline",
                    "fallback_reason": "timeout",
                    "prompt_source": prompt_source,
                }
                self._start_writer_cooldown("timeout")
            elif result.error_type is not None:
                logger.info("Writer pipeline failed, fallback to rules: %s", result.error_type)
                fallback_status_message = f"writer_failed_rule_fallback:{result.error_type}"
                fallback_metadata = {
                    "mode": "rule_fallback",
                    "fallback_source": "writer_pipeline",
                    "fallback_reason": result.error_type,
                    "prompt_source": prompt_source,
                }
                self._start_writer_cooldown(result.error_type)
            elif result.fallback_reason is not None:
                fallback_status_message = result.status_message or "writer_empty_output_rule_fallback"
                fallback_metadata = {
                    "mode": "rule_fallback",
                    "fallback_source": "writer_pipeline",
                    "fallback_reason": result.fallback_reason,
                    "prompt_source": prompt_source,
                    "tokens_in": result.usage_details.get("input") if result.usage_details else 0,
                    "tokens_out": result.usage_details.get("output") if result.usage_details else 0,
                    "tokens_total": result.usage_details.get("total") if result.usage_details else 0,
                }

            metadata = telemetry.finish(
                fallback_used=True,
                rule_vs_llm_path="llm_fallback",
                timeout_occurred=fallback_metadata.get("fallback_reason") == "timeout",
                llm_attempted=True,
                **fallback_metadata,
            )
            if flow_obs is not None:
                flow_obs.update(
                    output=fallback.text,
                    level="DEFAULT",
                    status_message=fallback_status_message,
                    metadata=metadata,
                )
            return GeneratedResponse(
                text=fallback.text,
                source=ResponseGeneratorSource.RULES,
                fallback_used=True,
                metadata=metadata,
            )

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
