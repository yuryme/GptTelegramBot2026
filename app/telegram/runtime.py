from aiogram import Bot, Dispatcher

from app.core.settings import get_settings
from app.telegram.handlers import create_router


def build_bot() -> Bot:
    settings = get_settings()
    return Bot(token=settings.telegram_bot_token)


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router())
    return dispatcher
