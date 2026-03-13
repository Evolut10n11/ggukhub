from __future__ import annotations

import uvicorn

from app.config import get_settings
from app.core.logging_setup import configure_logging


def main() -> None:
    configure_logging()
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.api_log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
