from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.core.bootstrap import build_runtime
from app.core.db import DatabaseRuntime
from app.core.services import AppServices


@dataclass(slots=True)
class AppRuntime:
    settings: Settings
    db: DatabaseRuntime
    services: AppServices

    async def init(self) -> None:
        await self.db.init()

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
