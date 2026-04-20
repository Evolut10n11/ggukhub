from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import nullcontext, suppress

import uvicorn

from app.config import Settings, get_settings
from app.core.logging_setup import configure_logging
from app.core.process_lock import BOT_LOCK_FILE, process_lock
from app.core.runtime import create_app_runtime
from app.main import create_app
from app.telegram.bot import configure_bot_ui, create_bot, create_dispatcher

logger = logging.getLogger(__name__)


async def _run_api_server(app, settings: Settings, stop_event: asyncio.Event) -> None:
    config = uvicorn.Config(
        app=app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.api_log_level,
        reload=False,
    )
    server = uvicorn.Server(config)
    server.capture_signals = nullcontext  # type: ignore[method-assign]

    async def _wait_for_stop() -> None:
        await stop_event.wait()
        server.should_exit = True

    watcher = asyncio.create_task(_wait_for_stop())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher


async def _run_polling(runtime, stop_event: asyncio.Event) -> None:
    settings = runtime.services.settings
    if not settings.telegram_bot_token:
        logger.info("TELEGRAM_BOT_TOKEN not set, Telegram polling disabled")
        return

    bot = create_bot(settings.telegram_bot_token)
    dispatcher = create_dispatcher(runtime.services)
    await configure_bot_ui(bot)

    async def _wait_for_stop() -> None:
        await stop_event.wait()
        with suppress(RuntimeError):
            await dispatcher.stop_polling()

    watcher = asyncio.create_task(_wait_for_stop())
    try:
        await dispatcher.start_polling(
            bot,
            handle_signals=False,
            close_bot_session=True,
        )
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher


async def _run_max_polling(runtime, stop_event: asyncio.Event, *, app=None) -> None:
    from app.max.polling import MaxPolling

    settings = runtime.services.settings
    poller = MaxPolling(settings, runtime.services)
    if app is not None:
        app.state.max_client = poller._client

    async def _wait_for_stop() -> None:
        await stop_event.wait()
        await poller.stop()

    watcher = asyncio.create_task(_wait_for_stop())
    try:
        await poller.start()
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher


async def _run_max_operator_polling(runtime, stop_event: asyncio.Event) -> None:
    from app.max.operator_polling import MaxOperatorPolling

    settings = runtime.services.settings
    poller = MaxOperatorPolling(settings, runtime.services)

    async def _wait_for_stop() -> None:
        await stop_event.wait()
        await poller.stop()

    watcher = asyncio.create_task(_wait_for_stop())
    try:
        await poller.start()
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher


def _install_signal_handlers(stop_event: asyncio.Event) -> list[signal.Signals]:
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
            installed.append(sig)
        except NotImplementedError:
            continue
    return installed


async def _main() -> None:
    settings = get_settings()
    stop_event = asyncio.Event()
    installed_signals = _install_signal_handlers(stop_event)

    lock_context = process_lock(BOT_LOCK_FILE) if not settings.telegram_use_webhook else nullcontext()
    with lock_context:
        runtime = create_app_runtime(settings)
        await runtime.init()
        try:
            app = create_app(settings=settings, runtime=runtime, manage_runtime=False)
            api_task = asyncio.create_task(_run_api_server(app, settings, stop_event))
            tasks = {api_task}

            if settings.telegram_use_webhook:
                logger.info("TELEGRAM_USE_WEBHOOK=true, stack runner starts API only")
            elif settings.telegram_bot_token:
                polling_task = asyncio.create_task(_run_polling(runtime, stop_event))
                tasks.add(polling_task)
            else:
                logger.info("TELEGRAM_BOT_TOKEN not set, Telegram bot disabled")

            if settings.max_enabled:
                max_task = asyncio.create_task(_run_max_polling(runtime, stop_event, app=app))
                tasks.add(max_task)
            else:
                logger.info("MAX_BOT_TOKEN not set, MAX bot disabled")

            if settings.max_operator_bot_enabled:
                max_op_task = asyncio.create_task(_run_max_operator_polling(runtime, stop_event))
                tasks.add(max_op_task)
            else:
                logger.info("MAX_OPERATOR_BOT_TOKEN not set, MAX operator bot disabled")

            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            first_error: BaseException | None = None
            for task in done:
                try:
                    await task
                except BaseException as error:  # noqa: BLE001
                    if first_error is None:
                        first_error = error

            stop_event.set()

            for task in pending:
                try:
                    await task
                except BaseException as error:  # noqa: BLE001
                    if first_error is None:
                        first_error = error

            if first_error is not None:
                raise first_error
        finally:
            for sig in installed_signals:
                asyncio.get_running_loop().remove_signal_handler(sig)
            await runtime.close()


def main() -> None:
    configure_logging()
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("Stack runner interrupted")


if __name__ == "__main__":
    main()
