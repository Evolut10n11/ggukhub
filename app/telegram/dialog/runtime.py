from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from typing import Any

logger = logging.getLogger(__name__)


class DialogRuntimeState:
    def __init__(self) -> None:
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._background_tasks: set[asyncio.Task[Any]] = set()

    def user_lock(self, user_id: int) -> asyncio.Lock:
        lock = self._user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._user_locks[user_id] = lock
        return lock

    def register_background_task(self, coro: Awaitable[Any]) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _on_done(done_task: asyncio.Task[Any]) -> None:
            self._background_tasks.discard(done_task)
            try:
                done_task.result()
            except Exception:
                logger.exception("Background task failed")

        task.add_done_callback(_on_done)

    def reset(self) -> None:
        self._user_locks.clear()
        self._background_tasks.clear()

    @property
    def user_locks(self) -> dict[int, asyncio.Lock]:
        return self._user_locks

    @property
    def background_tasks(self) -> set[asyncio.Task[Any]]:
        return self._background_tasks

    async def wait_background_tasks(self, timeout_seconds: float = 1.5) -> None:
        deadline = time.perf_counter() + timeout_seconds
        while time.perf_counter() < deadline:
            pending = [task for task in list(self._background_tasks) if not task.done()]
            if not pending:
                return
            await asyncio.sleep(0.01)

        pending = [task for task in list(self._background_tasks) if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
