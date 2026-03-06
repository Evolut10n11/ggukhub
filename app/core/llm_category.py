from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai_langfuse_extras.model import AgentConfig, openai_model_from_config

from app.config import Settings
from app.core.classifier import CategoryClassifier

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

    @property
    def enabled(self) -> bool:
        return bool(self._settings.use_llm and self._settings.llm_base_url and self._settings.llm_model)

    async def resolve(self, text: str) -> str | None:
        if not self.enabled:
            return None

        source = text.strip()
        if not source:
            return None

        try:
            config = AgentConfig(
                model=self._settings.llm_model,
                base_url=self._settings.llm_base_url,
                api_key=self._settings.llm_api_key or "local-no-key",
                model_settings={
                    # Qwen in your gateway emits reasoning; classification needs enough budget
                    # to reach final content token.
                    "max_tokens": max(512, min(self._settings.llm_max_tokens, 1024)),
                    "temperature": 0,
                },
            )
            model = openai_model_from_config(config)
            latin_source = _transliterate_ru(source)
            if latin_source != source.lower():
                user_prompt = f"Issue text: {source}\nTransliterated text: {latin_source}"
            else:
                user_prompt = f"Issue text: {source}"
            result = await _category_agent.run(
                user_prompt=user_prompt,
                deps=_Deps(instructions=self._build_instructions()),
                model=model,
            )
        except Exception as error:
            logger.warning("LLM category resolve failed: %s", error)
            return None

        content = str(result.output).strip()
        category = self._parse_category(content)
        if category is None:
            logger.warning("Cannot parse category from LLM response: %r", content)
        return category

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
        categories_text = "\n".join(f"- {code}: {categories_help.get(code, self._labels.get(code, code))}" for code in self._categories)
        return (
            "You are a strict classifier for housing maintenance incidents.\n"
            "Choose exactly ONE category code from the list.\n"
            "Output only the code, no explanations.\n"
            "Typos and colloquial phrasing are common; normalize mentally before classification.\n"
            "If uncertain, output other.\n"
            f"Category list:\n{categories_text}"
        )

    def _parse_category(self, content: str) -> str | None:
        value = content.strip().lower()
        if not value:
            return None

        if value in self._lookup:
            return self._lookup[value]

        # JSON-style response: {"category":"elevator"}
        for token in re.findall(r"[a-z_]+", value):
            if token in self._lookup:
                return self._lookup[token]

        return None
