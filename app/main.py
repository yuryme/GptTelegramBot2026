import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from aiogram.utils.token import TokenValidationError

from app.api.routes import router as api_router
from app.core.settings import get_settings
from app.observability.logging_config import configure_logging
from app.services.cost_control import MonthlyCostGuard
from app.services.webhook_dedup import WebhookDeduplicator
from app.telegram.runtime import build_bot, build_dispatcher

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.app_log_level)
    bot = None
    dispatcher = None
    try:
        bot = build_bot()
        dispatcher = build_dispatcher()
    except TokenValidationError:
        logger.warning("Telegram bot token is invalid. Webhook processing is disabled.")
    app.state.bot = bot
    app.state.dispatcher = dispatcher
    app.state.webhook_dedup = WebhookDeduplicator()
    app.state.cost_guard = MonthlyCostGuard(
        monthly_usd_limit=settings.openai_monthly_budget_usd,
        estimated_input_cost_per_1k=settings.openai_estimated_input_cost_per_1k,
        estimated_output_cost_per_1k=settings.openai_estimated_output_cost_per_1k,
    )
    logger.info("Application started")
    try:
        yield
    finally:
        if bot is not None:
            await bot.session.close()
        logger.info("Application stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(api_router)
    return app


app = create_app()
