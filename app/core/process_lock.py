from __future__ import annotations

import atexit
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

BOT_LOCK_FILE = Path("var/run/bot.lock")


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@contextmanager
def process_lock(lock_file: Path) -> Iterator[None]:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    if lock_file.exists():
        raw = lock_file.read_text(encoding="utf-8").strip()
        if raw.isdigit() and _is_process_alive(int(raw)):
            raise RuntimeError(
                f"Process lock is already held (pid={raw}). "
                "Stop the running instance before starting a new one."
            )
        lock_file.unlink(missing_ok=True)

    def _cleanup() -> None:
        lock_file.unlink(missing_ok=True)

    lock_file.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(_cleanup)
    try:
        yield
    finally:
        _cleanup()
