from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request

from app.core.bootstrap import build_services
from app.core.db import close_db, init_db
from app.telegram.bot import create_bot, create_dispatcher

services = build_services()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.services = services
    app.state.webhook_bot = None
    app.state.webhook_dispatcher = None

    if services.settings.telegram_use_webhook:
        if not services.settings.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required for webhook mode")
        app.state.webhook_bot = create_bot(services.settings.telegram_bot_token)
        app.state.webhook_dispatcher = create_dispatcher(services)

    try:
        yield
    finally:
        if app.state.webhook_bot is not None:
            await app.state.webhook_bot.session.close()
        await services.notifier.close()
        await close_db()


app = FastAPI(title=services.settings.app_name, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/bitrix/webhook")
async def bitrix_webhook(
    request: Request,
    x_bitrix_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    payload = await request.json()
    provided_secret = x_bitrix_secret or request.query_params.get("secret")
    result = await request.app.state.services.bitrix_webhook.handle(payload=payload, provided_secret=provided_secret)
    if not result["accepted"]:
        raise HTTPException(status_code=403, detail="Invalid Bitrix shared secret")
    return result


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    settings = request.app.state.services.settings
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
    rows = await request.app.state.services.storage.get_report_audits(report_id)
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
