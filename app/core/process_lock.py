from __future__ import annotations

import atexit
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

BOT_LOCK_FILE = Path(tempfile.gettempdir()) / "green-garden-bot.lock"


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
        # A lock owning *our own* pid cannot be a competing live instance — it is
        # a stale leftover. This is the common case in a container, where the bot
        # is always pid 1: after a non-graceful exit the pid=1 lock survives the
        # restart and os.kill(1, 0) always succeeds, deadlocking every start.
        if raw.isdigit() and int(raw) != os.getpid() and _is_process_alive(int(raw)):
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
