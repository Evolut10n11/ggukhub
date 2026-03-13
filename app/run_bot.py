from __future__ import annotations

import asyncio

from app.core.logging_setup import configure_logging
from app.core.process_lock import BOT_LOCK_FILE, process_lock
from app.core.runtime import create_app_runtime
from app.telegram.bot import run_polling

async def _main() -> None:
    with process_lock(BOT_LOCK_FILE):
        runtime = create_app_runtime()
        await runtime.init()
        try:
            await run_polling(runtime.services)
        finally:
            await runtime.close()


def main() -> None:
    configure_logging()
    asyncio.run(_main())


if __name__ == "__main__":
    main()
