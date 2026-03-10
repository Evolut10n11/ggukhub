from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.core.models import Base


def build_engine_kwargs(database_url: str) -> dict[str, object]:
    engine_kwargs: dict[str, object] = {"echo": False}
    if database_url.startswith("sqlite+aiosqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    return engine_kwargs


@dataclass(slots=True)
class DatabaseRuntime:
    settings: Settings
    engine: AsyncEngine = field(init=False)
    session_factory: async_sessionmaker[AsyncSession] = field(init=False)

    def __post_init__(self) -> None:
        self.engine = create_async_engine(
            self.settings.database_url,
            **build_engine_kwargs(self.settings.database_url),
        )
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()


def create_database_runtime(settings: Settings | None = None) -> DatabaseRuntime:
    return DatabaseRuntime(settings or get_settings())
