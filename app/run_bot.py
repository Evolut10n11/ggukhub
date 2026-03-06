from __future__ import annotations

import asyncio
import atexit
import logging
import os
from pathlib import Path

from app.core.bootstrap import build_services
from app.core.db import close_db, init_db
from app.telegram.bot import run_polling

LOCK_FILE = Path(".bot.lock")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except Exception:
        return False
    return True


def _acquire_lock() -> None:
    if LOCK_FILE.exists():
        raw = LOCK_FILE.read_text(encoding="utf-8").strip()
        if raw.isdigit() and _is_process_alive(int(raw)):
            raise RuntimeError(
                f"Bot is already running (pid={raw}). "
                "Stop existing instance before starting a new one."
            )
        LOCK_FILE.unlink(missing_ok=True)

    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(lambda: LOCK_FILE.unlink(missing_ok=True))


async def _main() -> None:
    _acquire_lock()
    services = build_services()
    await init_db()
    try:
        await run_polling(services)
    finally:
        await services.notifier.close()
        await close_db()


if __name__ == "__main__":
    asyncio.run(_main())
