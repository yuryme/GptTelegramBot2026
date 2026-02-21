import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core.settings import get_settings

router = APIRouter()
settings = get_settings()
logger = logging.getLogger(__name__)


def _extract_update_timestamp(update: dict) -> int | None:
    for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
        payload = update.get(key)
        if isinstance(payload, dict):
            ts = payload.get("date")
            if isinstance(ts, int):
                return ts
    return None


@router.get("/healthz")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.post(settings.telegram_webhook_path)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")

    dispatcher = request.app.state.dispatcher
    bot = request.app.state.bot
    if dispatcher is None or bot is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram runtime is disabled due to invalid bot token",
        )
    dedup = request.app.state.webhook_dedup
    update = await request.json()
    ts = _extract_update_timestamp(update)
    if ts is not None:
        age = int(datetime.now(timezone.utc).timestamp()) - ts
        if age > settings.webhook_max_update_age_seconds:
            logger.info("Stale update skipped: age_seconds=%s", age)
            return {"ok": True}
    update_id = update.get("update_id")
    if isinstance(update_id, int):
        if not dedup.mark_seen(update_id):
            logger.info("Duplicate webhook update skipped: update_id=%s", update_id)
            return {"ok": True}
    await dispatcher.feed_raw_update(bot=bot, update=update)
    return {"ok": True}
