import io
import logging
from uuid import uuid4
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from app.core.i18n import t
from app.core.settings import get_settings
from app.db.session import SessionLocal
from app.repositories.reminder_repository import ReminderRepository
from app.schemas.commands import CommandName
from app.services.guardrails import ChatRateLimiter
from app.services.llm_service import (
    LLMBudgetExceededError,
    LLMCircuitOpenError,
    LLMCommandValidationError,
    LLMRateLimitError,
    LLMService,
)
from app.services.reminder_service import ReminderService
from app.services.speech_service import SpeechToTextService

router = Router()
llm_service = LLMService()
speech_service = SpeechToTextService()
settings = get_settings()
logger = logging.getLogger(__name__)
chat_rate_limiter = ChatRateLimiter(
    max_requests=settings.chat_rate_limit_requests,
    window_seconds=settings.chat_rate_limit_window_seconds,
)
display_tz = ZoneInfo(settings.app_timezone)

BTN_SHOW_TODAY = t("btn_show_today")
BTN_SHOW_ALL = t("btn_show_all")
BTN_SETTINGS = t("btn_settings")
BTN_MODELS = t("btn_models")
BTN_LIMITS = t("btn_limits")
BTN_BACK = t("btn_back")
MAX_MODEL_BUTTONS = 12
_chat_model_choices: dict[int, dict[str, str]] = {}


def _main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SHOW_TODAY)],
            [KeyboardButton(text=BTN_SHOW_ALL)],
            [KeyboardButton(text=BTN_SETTINGS)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def _settings_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_MODELS)],
            [KeyboardButton(text=BTN_LIMITS)],
            [KeyboardButton(text=BTN_BACK)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def _models_keyboard(models: list[str]) -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton(text=model)] for model in models[:MAX_MODEL_BUTTONS]]
    keyboard.append([KeyboardButton(text=BTN_BACK)])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


def _format_run_at(dt) -> str:
    return dt.astimezone(display_tz).strftime("%d.%m.%Y %H:%M")


def _format_status(status: str) -> str:
    mapping = {
        "pending": t("status_pending"),
        "done": t("status_done"),
        "deleted": t("status_deleted"),
    }
    return mapping.get(status, status)


async def on_start_message(message: Message) -> None:
    await message.answer(
        t("start_choose_action"),
        reply_markup=_main_keyboard(),
    )


async def _handle_business_text(
    *,
    message: Message,
    text: str,
    source_text: str,
) -> None:
    if not chat_rate_limiter.allow(message.chat.id):
        await message.answer(t("too_many_requests"))
        return

    try:
        command = await llm_service.build_command(text)
    except LLMBudgetExceededError:
        await message.answer(t("llm_budget_exceeded"))
        return
    except LLMRateLimitError:
        await message.answer(t("llm_rate_limit"))
        return
    except LLMCircuitOpenError:
        await message.answer(t("llm_circuit_open"))
        return
    except LLMCommandValidationError:
        await message.answer(t("command_not_understood"))
        return
    except Exception:
        logger.exception("LLM request failed")
        await message.answer(t("processing_error"))
        return

    try:
        async with SessionLocal() as session:
            service = ReminderService(ReminderRepository(session))

            if command.command == CommandName.create:
                created = await service.create_from_command(chat_id=message.chat.id, command=command)
                if not created:
                    await message.answer(t("nothing_created"))
                    return
                await service._repository.log_action(
                    action_id=str(uuid4()),
                    chat_id=message.chat.id,
                    action_type="create",
                    target_scope="multi" if len(created) > 1 else "single",
                    source_text=source_text,
                    parsed_command=command.model_dump(mode="json"),
                    result_stats={"created": len(created), "matched": len(created), "changed": len(created)},
                )
                lines = [t("created_reminders")]
                for idx, item in enumerate(created, start=1):
                    lines.append(f"{idx}. #{item.id} | {_format_run_at(item.run_at)}")
                    lines.append(f"   {item.text}")
                await message.answer("\n".join(lines))
                return

            if command.command == CommandName.list_items:
                items = await service.list_from_command(chat_id=message.chat.id, command=command)
                if not items:
                    await message.answer(t("nothing_found"))
                    return
                await service._repository.log_action(
                    action_id=str(uuid4()),
                    chat_id=message.chat.id,
                    action_type="list",
                    target_scope="multi",
                    source_text=source_text,
                    parsed_command=command.model_dump(mode="json"),
                    result_stats={"matched": len(items), "created": 0, "changed": 0},
                )
                lines = [t("found_reminders")]
                for idx, item in enumerate(items, start=1):
                    rec = f"{t('recurrence_prefix')}{item.recurrence_rule}" if item.recurrence_rule else ""
                    lines.append(f"{idx}. #{item.id} [{_format_status(item.status)}] | {_format_run_at(item.run_at)}{rec}")
                    lines.append(f"   {item.text}")
                await message.answer("\n".join(lines))
                return

            if command.command == CommandName.delete:
                deleted = await service.delete_from_command(chat_id=message.chat.id, command=command)
                if deleted.deleted_count == 0:
                    await message.answer(t("deleted_nothing"))
                    return
                await service._repository.log_action(
                    action_id=str(uuid4()),
                    chat_id=message.chat.id,
                    action_type="delete",
                    target_scope="multi" if deleted.deleted_count > 1 else "single",
                    source_text=source_text,
                    parsed_command=command.model_dump(mode="json"),
                    result_stats={"matched": len(deleted.items), "created": 0, "changed": deleted.deleted_count},
                )
                lines = [t("deleted_count").format(count=deleted.deleted_count)]
                for idx, item in enumerate(deleted.items, start=1):
                    lines.append(f"{idx}. #{item.id} | {_format_run_at(item.run_at)}")
                    lines.append(f"   {item.text}")
                await message.answer("\n".join(lines))
                return
    except Exception:
        logger.exception("Business command handling failed")
        await message.answer(t("processing_error"))
        return

    await message.answer(t("command_not_supported"))


@router.message(F.text)
async def on_text_message(message: Message) -> None:
    if not message.text:
        await message.answer(t("need_text"))
        return

    text = message.text.strip()
    if text.startswith("/start"):
        await on_start_message(message)
        return

    text_lc = text.lower()
    if text == BTN_SETTINGS or text_lc.startswith(BTN_SETTINGS.lower()):
        await message.answer(t("settings_section"), reply_markup=_settings_keyboard())
        return
    if text == BTN_BACK or text_lc == BTN_BACK.lower():
        _chat_model_choices.pop(message.chat.id, None)
        await message.answer(t("main_menu"), reply_markup=_main_keyboard())
        return
    if text == BTN_MODELS or text_lc.startswith(BTN_MODELS.lower()):
        models = await llm_service.list_accessible_models()
        _chat_model_choices[message.chat.id] = {model: model for model in models}
        lines = [t("available_models")]
        for model in models[:MAX_MODEL_BUTTONS]:
            price = llm_service.get_model_price_per_1m(model)
            if price is None:
                lines.append(f"- {model}: {t('price_unknown')}")
            else:
                lines.append(f"- {model}: input ${price[0]:.2f}/1M, output ${price[1]:.2f}/1M")
        lines.append(t("current_model").format(model=llm_service.active_model))
        await message.answer(
            "\n".join(lines),
            reply_markup=_models_keyboard(models),
        )
        return
    if text == BTN_LIMITS or text_lc.startswith(BTN_LIMITS.lower()):
        account_snapshot = await llm_service.get_account_limit_snapshot()
        if account_snapshot is not None:
            await message.answer(
                "\n".join(
                    [
                        t("api_limit").format(value=account_snapshot["hard_limit_usd"]),
                        t("api_spent").format(value=account_snapshot["spent_usd"]),
                        t("api_remaining").format(value=account_snapshot["remaining_usd"]),
                        "",
                        t("local_limit").format(value=settings.openai_monthly_budget_usd),
                    ]
                ),
                reply_markup=_settings_keyboard(),
            )
            return
        await message.answer(
            "\n".join(
                [
                    t("monthly_limit").format(value=settings.openai_monthly_budget_usd),
                    t("input_cost").format(value=settings.openai_estimated_input_cost_per_1k),
                    t("output_cost").format(value=settings.openai_estimated_output_cost_per_1k),
                    t("api_limit_unavailable"),
                ]
            ),
            reply_markup=_settings_keyboard(),
        )
        return

    model_choices = _chat_model_choices.get(message.chat.id, {})
    if text in model_choices:
        selected = model_choices[text]
        llm_service.set_active_model(selected)
        await message.answer(
            t("active_model_changed").format(model=selected),
            reply_markup=_settings_keyboard(),
        )
        return

    await _handle_business_text(message=message, text=text, source_text=text)


async def on_voice_message(message: Message) -> None:
    media = message.voice or message.audio
    if media is None:
        await message.answer(t("voice_unreadable"))
        return

    file_id = getattr(media, "file_id", None)
    if not file_id:
        await message.answer(t("voice_file_missing"))
        return

    filename = "voice.ogg"
    file_name_attr = getattr(media, "file_name", None)
    if isinstance(file_name_attr, str) and file_name_attr.strip():
        filename = file_name_attr.strip()

    await message.answer(t("voice_recognizing"))
    try:
        tg_file = await message.bot.get_file(file_id)
        if not tg_file.file_path:
            await message.answer(t("voice_file_unavailable"))
            return
        buffer = io.BytesIO()
        await message.bot.download_file(tg_file.file_path, destination=buffer)
        transcript = await speech_service.transcribe_bytes(
            payload=buffer.getvalue(),
            filename=filename,
        )
    except Exception:
        logger.exception("Voice message handling failed")
        await message.answer(t("voice_processing_error"))
        return

    if not transcript:
        await message.answer(t("voice_not_recognized"))
        return

    await message.answer(t("voice_recognized").format(text=transcript))
    await _handle_business_text(message=message, text=transcript, source_text=f"[voice] {transcript}")


def create_router() -> Router:
    runtime_router = Router()
    runtime_router.message.register(on_start_message, CommandStart())
    runtime_router.message.register(on_text_message, F.text)
    runtime_router.message.register(on_voice_message, F.voice | F.audio)
    return runtime_router
