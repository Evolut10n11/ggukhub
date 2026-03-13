from __future__ import annotations

import builtins
import importlib.util
import sys
from pathlib import Path

import pytest

from app.config.settings import ALLOWED_LLM_MODEL, Settings
from app.core.classifier import CategoryClassifier


def _load_module_without_llm_deps(monkeypatch: pytest.MonkeyPatch):
    original_import = builtins.__import__
    blocked_prefixes = ("langfuse", "pydantic_ai", "pydantic_ai_langfuse_extras")

    def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith(blocked_prefixes):
            raise ImportError(f"blocked import: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    module_path = Path(__file__).resolve().parents[1] / "app" / "core" / "llm_category.py"
    spec = importlib.util.spec_from_file_location("tests.temp_llm_category_without_deps", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_resolver_falls_back_when_optional_llm_deps_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module_without_llm_deps(monkeypatch)
    classifier = CategoryClassifier({"other": {"label": "Other", "keywords": []}})
    settings = Settings(
        telegram_bot_token="x",
        use_llm=True,
        llm_model=ALLOWED_LLM_MODEL,
        llm_base_url="http://qwen.local/v1",
    )

    resolver = module.LLMCategoryResolver(settings=settings, classifier=classifier)
    result = await resolver.resolve("Лифт не работает")

    assert resolver.enabled is False
    assert result.category is None
    assert result.fallback_used is True
    assert result.metadata["reason"] == "dependencies_unavailable"
