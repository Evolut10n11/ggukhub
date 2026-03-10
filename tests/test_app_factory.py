from __future__ import annotations

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
