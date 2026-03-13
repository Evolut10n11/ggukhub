from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request

from app.config import Settings, get_settings
from app.core.runtime import AppRuntime, create_app_runtime
from app.telegram.bot import configure_bot_ui, create_bot, create_dispatcher


async def _bind_runtime(app: FastAPI, runtime: AppRuntime) -> None:
    app.state.runtime = runtime
    app.state.services = runtime.services
    app.state.webhook_bot = None
    app.state.webhook_dispatcher = None

    if runtime.services.settings.telegram_use_webhook:
        if not runtime.services.settings.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required for webhook mode")
        app.state.webhook_bot = create_bot(runtime.services.settings.telegram_bot_token)
        app.state.webhook_dispatcher = create_dispatcher(runtime.services)
        await configure_bot_ui(app.state.webhook_bot)


async def _release_runtime(app: FastAPI, runtime: AppRuntime, *, close_runtime: bool) -> None:
    if app.state.webhook_bot is not None:
        await app.state.webhook_bot.session.close()
    if close_runtime:
        await runtime.close()


def create_app(
    settings: Settings | None = None,
    *,
    runtime: AppRuntime | None = None,
    manage_runtime: bool | None = None,
) -> FastAPI:
    if settings is not None:
        cfg = settings
    elif runtime is not None:
        cfg = runtime.settings
    else:
        cfg = get_settings()
    should_manage_runtime = runtime is None if manage_runtime is None else manage_runtime

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        active_runtime = runtime
        if active_runtime is None:
            active_runtime = create_app_runtime(cfg)
            await active_runtime.init()
        await _bind_runtime(app, active_runtime)

        try:
            yield
        finally:
            await _release_runtime(app, active_runtime, close_runtime=should_manage_runtime)

    app = FastAPI(title=cfg.app_name, lifespan=lifespan)
    _register_routes(app)
    return app


def _runtime_from_request(request: Request) -> AppRuntime:
    return request.app.state.runtime


def _register_routes(app: FastAPI) -> None:
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/bitrix/webhook")
    async def bitrix_webhook(
        request: Request,
        x_bitrix_secret: str | None = Header(default=None),
    ) -> dict[str, Any]:
        runtime = _runtime_from_request(request)
        payload = await request.json()
        provided_secret = x_bitrix_secret or request.query_params.get("secret")
        result = await runtime.services.bitrix_webhook.handle(payload=payload, provided_secret=provided_secret)
        if not result.accepted:
            raise HTTPException(status_code=403, detail="Invalid Bitrix shared secret")
        return result.to_dict()

    @app.post("/telegram/webhook")
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, bool]:
        runtime = _runtime_from_request(request)
        settings = runtime.services.settings
        if not settings.telegram_use_webhook:
            raise HTTPException(status_code=503, detail="Telegram webhook mode is disabled")
        if settings.telegram_webhook_secret and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
            raise HTTPException(status_code=403, detail="Invalid Telegram secret token")

        payload = await request.json()
        update = Update.model_validate(payload)
        await request.app.state.webhook_dispatcher.feed_update(request.app.state.webhook_bot, update)
        return {"ok": True}

    @app.get("/reports/{report_id}/audit")
    async def report_audit(report_id: int, request: Request) -> dict[str, Any]:
        runtime = _runtime_from_request(request)
        rows = await runtime.services.storage.get_report_audits(report_id)
        return {
            "report_id": report_id,
            "items": [
                {
                    "id": row.id,
                    "stage": row.stage,
                    "regulation_version": row.regulation_version,
                    "payload": json.loads(row.payload_json),
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ],
        }


app = create_app()
