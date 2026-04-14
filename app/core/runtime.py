from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field

from app.config import Settings, get_settings
from app.core.bootstrap import build_runtime
from app.core.db import DatabaseRuntime
from app.core.services import AppServices

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppRuntime:
    settings: Settings
    db: DatabaseRuntime
    services: AppServices
    _speech_warmup_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    async def init(self) -> None:
        await self.db.init()
        await self._validate_bitrix_fields()
        self._start_speech_warm_up()

    async def _validate_bitrix_fields(self) -> None:
        if not self.services.bitrix_service.enabled:
            return
        try:
            missing = await self.services.bitrix_service.validate_fields()
            if missing:
                logger.warning("Missing Bitrix custom fields: %s", ", ".join(missing))
            else:
                logger.info("Bitrix custom fields validated successfully")
        except Exception as exc:
            logger.warning("Bitrix field validation skipped: %s", exc)

    def _start_speech_warm_up(self) -> None:
        if self._speech_warmup_task is not None:
            return
        if not hasattr(self.services.speech, "warm_up"):
            return
        if self.settings.speech_enabled and self.settings.speech_base_url.strip().lower().startswith("local://"):
            logger.info("Speech warm-up skipped at startup for local mode")
            return
        self._speech_warmup_task = asyncio.create_task(self._warm_up_speech())
        logger.info("Speech warm-up scheduled in background")

    async def _warm_up_speech(self) -> None:
        if hasattr(self.services.speech, "warm_up"):
            try:
                await self.services.speech.warm_up()
                logger.info("Speech model pre-loaded")
            except Exception as exc:
                logger.warning("Speech warm-up failed: %s", exc)
            finally:
                self._speech_warmup_task = None

    async def close(self) -> None:
        if self._speech_warmup_task is not None:
            self._speech_warmup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._speech_warmup_task
        if self.services.max_operator_service is not None:
            await self.services.max_operator_service.close()
        if hasattr(self.services.speech, "close"):
            self.services.speech.close()
        await self.services.notifier.close()
        await self.services.bitrix_client.close()
        await self.db.close()


def create_app_runtime(settings: Settings | None = None) -> AppRuntime:
    cfg = settings or get_settings()
    db, services = build_runtime(cfg)
    return AppRuntime(settings=cfg, db=db, services=services)
