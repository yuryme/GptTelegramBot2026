import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from aiogram.utils.token import TokenValidationError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.api.routes import router as api_router
from app.core.settings import get_settings
from app.observability.logging_config import configure_logging
from app.services.cost_control import MonthlyCostGuard
from app.services.reminder_dispatcher import dispatch_due_reminders
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
    scheduler = AsyncIOScheduler(timezone="UTC")
    app.state.scheduler = scheduler
    if bot is not None:
        scheduler.add_job(
            dispatch_due_reminders,
            "interval",
            seconds=15,
            kwargs={"bot": bot, "batch_size": 100},
            max_instances=1,
            coalesce=True,
            id="due-reminders-dispatch",
            replace_existing=True,
        )
        scheduler.start()
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
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler is not None and scheduler.running:
            scheduler.shutdown(wait=False)
        if bot is not None:
            await bot.session.close()
        logger.info("Application stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(api_router)
    return app


app = create_app()
