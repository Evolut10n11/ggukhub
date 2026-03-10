from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.core.services import AppServices
from app.telegram.handlers import router
from app.telegram.middlewares import ServicesMiddleware

logger = logging.getLogger(__name__)

def build_bot_commands() -> list[BotCommand]:
    return [
        BotCommand(command="start", description="Открыть бота"),
        BotCommand(command="new", description="Новая заявка"),
        BotCommand(command="status", description="Статус заявки"),
    ]


def create_bot(token: str) -> Bot:
    return Bot(token=token)


def create_dispatcher(services: AppServices) -> Dispatcher:
    dispatcher = Dispatcher()
    middleware = ServicesMiddleware(services)
    dispatcher.message.middleware(middleware)
    dispatcher.callback_query.middleware(middleware)
    dispatcher.include_router(router)
    return dispatcher


async def configure_bot_ui(bot: Bot) -> None:
    try:
        await bot.set_my_commands(build_bot_commands())
    except Exception as error:
        logger.warning("Cannot configure Telegram bot commands: %s", error)


async def run_polling(services: AppServices) -> None:
    if not services.settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    bot = create_bot(services.settings.telegram_bot_token)
    dispatcher = create_dispatcher(services)
    try:
        await configure_bot_ui(bot)
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
