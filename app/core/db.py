from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.core.models import Base


def build_engine_kwargs(database_url: str) -> dict[str, object]:
    engine_kwargs: dict[str, object] = {"echo": False}
    if database_url.startswith("sqlite+aiosqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    return engine_kwargs


def _sqlite_file_path(database_url: str) -> Path | None:
    prefixes = ("sqlite+aiosqlite:///", "sqlite:///")
    for prefix in prefixes:
        if database_url.startswith(prefix):
            raw_path = database_url.removeprefix(prefix).split("?", 1)[0].strip()
            if not raw_path or raw_path == ":memory:":
                return None
            return Path(raw_path)
    return None


def ensure_database_parent_dir(database_url: str) -> None:
    db_path = _sqlite_file_path(database_url)
    if db_path is None:
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class DatabaseRuntime:
    settings: Settings
    engine: AsyncEngine = field(init=False)
    session_factory: async_sessionmaker[AsyncSession] = field(init=False)

    def __post_init__(self) -> None:
        ensure_database_parent_dir(self.settings.database_url)
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
