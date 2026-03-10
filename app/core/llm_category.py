from __future__ import annotations

import asyncio
import os
import logging
import re
from contextlib import nullcontext
from dataclasses import dataclass

from langfuse import Langfuse
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai_langfuse_extras.model import AgentConfig, openai_model_from_config

from app.core.category_resolution import CategoryResolutionResult, CategoryResolutionSource
from app.config import Settings
from app.core.classifier import CategoryClassifier
from app.core.telemetry import start_flow_telemetry

logger = logging.getLogger(__name__)

_RU_TO_LATIN = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def _transliterate_ru(value: str) -> str:
    result: list[str] = []
    for symbol in value.lower():
        result.append(_RU_TO_LATIN.get(symbol, symbol))
    return "".join(result)


@dataclass(slots=True)
class _Deps:
    instructions: str


_category_agent = Agent(model=TestModel(), deps_type=_Deps, name="uk_category_agent")


@_category_agent.instructions
async def _instructions(ctx: RunContext[_Deps]) -> str:
    return ctx.deps.instructions


class LLMCategoryResolver:
    def __init__(self, settings: Settings, classifier: CategoryClassifier):
        self._settings = settings
        self._categories = classifier.categories()
        self._labels = {code: classifier.label(code) for code in self._categories}
        self._lookup = {code.lower(): code for code in self._categories}
        self._instructions_text = self._build_instructions()
        self._model: object | None = None
        self._langfuse: Langfuse | None = None

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
                    logger.info("Langfuse tracing enabled for LLMCategoryResolver")
                else:
                    logger.info("Langfuse auth check failed for category resolver, running without category tracing")
                    self._langfuse = None
            except Exception as error:
                logger.info("Langfuse setup failed for category resolver: %s", error)
                self._langfuse = None

    @property
    def enabled(self) -> bool:
        return bool(self._settings.use_llm and self._settings.llm_base_url and self._settings.llm_model)

    def _effective_timeout_seconds(self) -> float:
        return min(
            self._settings.llm_category_timeout_seconds,
            self._settings.llm_category_soft_timeout_seconds,
        )

    def _start_flow_observation(self, *, input_text: str, effective_timeout: float):
        if not self._langfuse:
            return nullcontext(None)
        return self._langfuse.start_as_current_observation(
            name="category_resolver run",
            as_type="agent",
            input=input_text,
            level="DEFAULT",
            metadata={
                "component": "llm_category",
                "flow": "category_resolution",
                "budget_ms": int(effective_timeout * 1000),
                "hard_timeout_ms": int(self._settings.llm_category_timeout_seconds * 1000),
                "model_name": self._settings.llm_model,
            },
        )

    def _start_generation_observation(self, *, parent_obs: object | None, input_text: str):
        params = dict(
            name=f"chat {self._settings.llm_model}",
            as_type="generation",
            input=input_text,
            level="DEFAULT",
            model=self._settings.llm_model,
            model_parameters={
                "temperature": 0,
                "max_tokens": min(self._settings.llm_max_tokens, self._settings.llm_category_max_tokens),
                "stage": "category_resolution",
            },
        )
        if parent_obs is not None and hasattr(parent_obs, "start_as_current_observation"):
            return parent_obs.start_as_current_observation(**params)
        if self._langfuse:
            return self._langfuse.start_as_current_observation(**params)
        return nullcontext(None)

    async def resolve(self, text: str) -> CategoryResolutionResult:
        effective_timeout = self._effective_timeout_seconds()
        telemetry = start_flow_telemetry(
            "category_resolution",
            "llm_resolver",
            budget_ms=int(effective_timeout * 1000),
            llm_enabled=self.enabled,
            model_name=self._settings.llm_model,
            hard_timeout_ms=int(self._settings.llm_category_timeout_seconds * 1000),
        )
        if not self.enabled:
            return self._fallback_result(
                reason="disabled",
                metadata=telemetry.finish(
                    fallback_used=True,
                    timeout_occurred=False,
                    rule_vs_llm_path="llm_disabled",
                    llm_attempted=False,
                ),
            )

        source = text.strip()
        if not source:
            return self._fallback_result(
                reason="empty_input",
                metadata=telemetry.finish(
                    fallback_used=True,
                    timeout_occurred=False,
                    rule_vs_llm_path="empty_input",
                    llm_attempted=False,
                ),
            )

        latin_source = _transliterate_ru(source)
        if latin_source != source.lower():
            user_prompt = f"Issue text: {source}\nTransliterated text: {latin_source}"
        else:
            user_prompt = f"Issue text: {source}"

        with self._start_flow_observation(input_text=user_prompt, effective_timeout=effective_timeout) as flow_obs:
            with self._start_generation_observation(parent_obs=flow_obs, input_text=user_prompt) as generation_obs:
                try:
                    result = await asyncio.wait_for(
                        _category_agent.run(
                            user_prompt=user_prompt,
                            deps=_Deps(instructions=self._instructions_text),
                            model=self._get_model(),
                        ),
                        timeout=effective_timeout,
                    )
                    content = str(result.output).strip()
                    usage_details = self._usage_details_from_result(result)
                    if generation_obs is not None:
                        generation_obs.update(output=content, usage_details=usage_details, level="DEFAULT")
                except asyncio.TimeoutError:
                    logger.info(
                        "LLM category resolve timed out after %.2fs",
                        effective_timeout,
                    )
                    metadata = telemetry.finish(
                        fallback_used=True,
                        timeout_occurred=True,
                        rule_vs_llm_path="llm_timeout",
                        llm_attempted=True,
                    )
                    if generation_obs is not None:
                        generation_obs.update(
                            level="DEFAULT",
                            status_message="category_timeout_rule_fallback",
                            metadata=metadata,
                        )
                    if flow_obs is not None:
                        flow_obs.update(
                            level="DEFAULT",
                            status_message="category_timeout_rule_fallback",
                            metadata=metadata,
                        )
                    return self._fallback_result(
                        reason="timeout",
                        timed_out=True,
                        metadata=metadata,
                    )
                except Exception as error:
                    logger.info("LLM category resolve failed, fallback to rules: %s", error)
                    metadata = telemetry.finish(
                        fallback_used=True,
                        timeout_occurred=False,
                        rule_vs_llm_path="llm_failed",
                        llm_attempted=True,
                        error_type=type(error).__name__,
                    )
                    if generation_obs is not None:
                        generation_obs.update(
                            level="DEFAULT",
                            status_message="category_failed_rule_fallback",
                            metadata=metadata,
                        )
                    if flow_obs is not None:
                        flow_obs.update(
                            level="DEFAULT",
                            status_message="category_failed_rule_fallback",
                            metadata=metadata,
                        )
                    return self._fallback_result(
                        reason=type(error).__name__,
                        metadata=metadata,
                    )

            category = self._parse_category(content)
            if category is None:
                logger.info("Cannot parse category from LLM response, fallback to rules: %r", content)
                metadata = telemetry.finish(
                    raw_output=content,
                    fallback_used=True,
                    timeout_occurred=False,
                    rule_vs_llm_path="llm_parse_failed",
                    llm_attempted=True,
                    tokens_in=usage_details.get("input") if usage_details else 0,
                    tokens_out=usage_details.get("output") if usage_details else 0,
                    tokens_total=usage_details.get("total") if usage_details else 0,
                )
                if flow_obs is not None:
                    flow_obs.update(
                        output=content,
                        level="DEFAULT",
                        status_message="category_parse_failed_rule_fallback",
                        metadata=metadata,
                    )
                return self._fallback_result(
                    reason="parse_failed",
                    raw_output=content,
                    metadata=metadata,
                )

            metadata = telemetry.finish(
                raw_output=content,
                fallback_used=False,
                timeout_occurred=False,
                rule_vs_llm_path="llm",
                llm_attempted=True,
                tokens_in=usage_details.get("input") if usage_details else 0,
                tokens_out=usage_details.get("output") if usage_details else 0,
                tokens_total=usage_details.get("total") if usage_details else 0,
            )
            if flow_obs is not None:
                flow_obs.update(output=content, level="DEFAULT", metadata=metadata)
            return CategoryResolutionResult(
                category=category,
                source=CategoryResolutionSource.LLM,
                raw_output=content,
                metadata=metadata,
            )

    def _build_instructions(self) -> str:
        categories_help = {
            "water_off": "water supply off",
            "water_leak": "leak, flooding, dripping pipe/ceiling",
            "electricity_off": "power outage, no lights",
            "elevator": "elevator issue, stuck cabin",
            "heating": "cold radiators, no heating",
            "sewage": "sewage, drain blockage, bad smell",
            "intercom": "intercom or entry panel issue",
            "cleaning": "dirty entrance, trash, cleaning needed",
            "other": "unclear or none of the above",
        }
        categories_text = "\n".join(
            f"- {code}: {categories_help.get(code, self._labels.get(code, code))}"
            for code in self._categories
        )
        return (
            "You are a strict classifier for housing maintenance incidents.\n"
            "Choose exactly ONE category code from the list.\n"
            "Output only the code, no explanations.\n"
            "Typos and colloquial phrasing are common; normalize mentally before classification.\n"
            "If uncertain, output other.\n"
            f"Category list:\n{categories_text}"
        )

    def _get_model(self) -> object:
        if self._model is not None:
            return self._model

        config = AgentConfig(
            model=self._settings.llm_model,
            base_url=self._settings.llm_base_url,
            api_key=self._settings.llm_api_key or "local-no-key",
            model_settings={
                "max_tokens": min(self._settings.llm_max_tokens, self._settings.llm_category_max_tokens),
                "temperature": 0,
            },
        )
        self._model = openai_model_from_config(config)
        return self._model

    def _parse_category(self, content: str) -> str | None:
        value = content.strip().lower()
        if not value:
            return None

        if value in self._lookup:
            return self._lookup[value]

        for token in re.findall(r"[a-z_]+", value):
            if token in self._lookup:
                return self._lookup[token]

        return None

    @staticmethod
    def _usage_details_from_result(result: object) -> dict[str, int] | None:
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

    @staticmethod
    def _fallback_result(
        *,
        reason: str,
        raw_output: str | None = None,
        timed_out: bool = False,
        metadata: dict[str, object] | None = None,
    ) -> CategoryResolutionResult:
        fallback_metadata = {"reason": reason}
        if metadata:
            fallback_metadata.update(metadata)
        return CategoryResolutionResult(
            category=None,
            source=CategoryResolutionSource.LLM,
            raw_output=raw_output,
            timed_out=timed_out,
            fallback_used=True,
            metadata=fallback_metadata,
        )
