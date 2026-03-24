from __future__ import annotations

import logging
from dataclasses import dataclass

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

    async def init(self) -> None:
        await self.db.init()
        await self._validate_bitrix_fields()
        await self._warm_up_speech()

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

    async def _warm_up_speech(self) -> None:
        if hasattr(self.services.speech, "warm_up"):
            try:
                await self.services.speech.warm_up()
                logger.info("Speech model pre-loaded")
            except Exception as exc:
                logger.warning("Speech warm-up failed: %s", exc)

    async def close(self) -> None:
        if hasattr(self.services.speech, "close"):
            self.services.speech.close()
        await self.services.notifier.close()
        await self.services.bitrix_client.close()
        await self.db.close()


def create_app_runtime(settings: Settings | None = None) -> AppRuntime:
    cfg = settings or get_settings()
    db, services = build_runtime(cfg)
    return AppRuntime(settings=cfg, db=db, services=services)
