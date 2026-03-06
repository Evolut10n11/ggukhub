from __future__ import annotations

from aiogram import Bot, Dispatcher

from app.core.services import AppServices
from app.telegram.handlers import router
from app.telegram.middlewares import ServicesMiddleware


def create_bot(token: str) -> Bot:
    return Bot(token=token)


def create_dispatcher(services: AppServices) -> Dispatcher:
    dispatcher = Dispatcher()
    middleware = ServicesMiddleware(services)
    dispatcher.message.middleware(middleware)
    dispatcher.callback_query.middleware(middleware)
    dispatcher.include_router(router)
    return dispatcher


async def run_polling(services: AppServices) -> None:
    if not services.settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    bot = create_bot(services.settings.telegram_bot_token)
    dispatcher = create_dispatcher(services)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()

