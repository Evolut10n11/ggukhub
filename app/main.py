from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request

from app.config import Settings, get_settings
from app.core.runtime import AppRuntime, create_app_runtime
from app.telegram.bot import configure_bot_ui, create_bot, create_dispatcher

logger = logging.getLogger(__name__)

MAX_WEBHOOK_BODY_BYTES = 256 * 1024  # 256 KB


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
    async def health(request: Request) -> dict[str, Any]:
        runtime = _runtime_from_request(request)
        db_ok = False
        try:
            await runtime.services.storage.health_check()
            db_ok = True
        except Exception:
            logger.warning("Health check DB error", exc_info=True)
        status = "ok" if db_ok else "degraded"
        return {
            "status": status,
            "db": "ok" if db_ok else "error",
            "bitrix": "enabled" if runtime.services.bitrix_service.enabled else "disabled",
        }

    @app.post("/bitrix/webhook")
    async def bitrix_webhook(
        request: Request,
        x_bitrix_secret: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _check_body_size(request)
        runtime = _runtime_from_request(request)
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
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
        _check_body_size(request)
        runtime = _runtime_from_request(request)
        settings = runtime.services.settings
        if not settings.telegram_use_webhook:
            raise HTTPException(status_code=503, detail="Telegram webhook mode is disabled")
        if settings.telegram_webhook_secret and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
            raise HTTPException(status_code=403, detail="Invalid Telegram secret token")

        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
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
                    "payload": _safe_json_loads(row.payload_json),
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ],
        }


def _check_body_size(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")


def _safe_json_loads(raw: str | None) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Corrupted audit payload JSON: %.100s", raw)
        return {"_raw": raw}


app = create_app()
