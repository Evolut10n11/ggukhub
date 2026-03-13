from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config.settings import Settings
from app.main import create_app


def test_create_app_does_not_initialize_runtime_before_lifespan(monkeypatch) -> None:
    called = False

    def fake_create_app_runtime(settings: Settings | None = None):
        nonlocal called
        _ = settings
        called = True
        raise AssertionError("runtime should not be created during app factory call")

    monkeypatch.setattr("app.main.create_app_runtime", fake_create_app_runtime)

    app = create_app(Settings(telegram_bot_token="x", use_llm=False))

    assert app.title == "Green Garden UK Assistant"
    assert called is False


@pytest.mark.asyncio
async def test_create_app_can_reuse_external_runtime_without_managing_it(monkeypatch) -> None:
    class DummyRuntime:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings
            self.services = SimpleNamespace(settings=settings)
            self.init_calls = 0
            self.close_calls = 0

        async def init(self) -> None:
            self.init_calls += 1

        async def close(self) -> None:
            self.close_calls += 1

    def fake_create_app_runtime(settings: Settings | None = None):
        _ = settings
        raise AssertionError("external runtime should be reused as-is")

    monkeypatch.setattr("app.main.create_app_runtime", fake_create_app_runtime)

    settings = Settings(telegram_bot_token="x", use_llm=False)
    runtime = DummyRuntime(settings)
    app = create_app(settings=settings, runtime=runtime, manage_runtime=False)

    async with app.router.lifespan_context(app):
        assert app.state.runtime is runtime
        assert app.state.services is runtime.services

    assert runtime.init_calls == 0
    assert runtime.close_calls == 0
