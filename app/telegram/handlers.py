from aiogram import F, Router
from aiogram.types import Message
from zoneinfo import ZoneInfo

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

router = Router()
llm_service = LLMService()
settings = get_settings()
chat_rate_limiter = ChatRateLimiter(
    max_requests=settings.chat_rate_limit_requests,
    window_seconds=settings.chat_rate_limit_window_seconds,
)
display_tz = ZoneInfo(settings.app_timezone)


def _format_run_at(dt) -> str:
    return dt.astimezone(display_tz).strftime("%d.%m.%Y %H:%M")


def _format_status(status: str) -> str:
    mapping = {
        "pending": "в ожидании",
        "done": "выполнено",
    }
    return mapping.get(status, status)


@router.message(F.text)
async def on_text_message(message: Message) -> None:
    if not message.text:
        await message.answer("Нужен текст запроса.")
        return
    if not chat_rate_limiter.allow(message.chat.id):
        await message.answer("Слишком много запросов. Подождите немного и попробуйте снова.")
        return

    try:
        command = await llm_service.build_command(message.text)
    except LLMBudgetExceededError:
        await message.answer("Лимит запросов к модели на текущий месяц исчерпан.")
        return
    except LLMRateLimitError:
        await message.answer("Сервис модели временно недоступен: превышен лимит/квота OpenAI. Попробуйте позже.")
        return
    except LLMCircuitOpenError:
        await message.answer("Сервис модели временно перегружен. Попробуйте через минуту.")
        return
    except LLMCommandValidationError:
        await message.answer("Не удалось понять команду. Уточните текст запроса.")
        return
    except Exception:
        await message.answer("Ошибка обработки запроса. Попробуйте еще раз.")
        return

    async with SessionLocal() as session:
        service = ReminderService(ReminderRepository(session))

        if command.command == CommandName.create:
            created = await service.create_from_command(chat_id=message.chat.id, command=command)
            lines = ["Напоминания созданы:"]
            for idx, item in enumerate(created, start=1):
                rec = f", повтор: {item.recurrence_rule}" if item.recurrence_rule else ""
                lines.append(f"{idx}. #{item.id} | {_format_run_at(item.run_at)}{rec}")
                lines.append(f"   {item.text}")
            await message.answer("\n".join(lines))
            return

        if command.command == CommandName.list_items:
            items = await service.list_from_command(chat_id=message.chat.id, command=command)
            if not items:
                await message.answer("Напоминания не найдены.")
                return
            lines = ["Найденные напоминания:"]
            for idx, item in enumerate(items, start=1):
                rec = f", повтор: {item.recurrence_rule}" if item.recurrence_rule else ""
                lines.append(f"{idx}. #{item.id} [{_format_status(item.status)}] | {_format_run_at(item.run_at)}{rec}")
                lines.append(f"   {item.text}")
            await message.answer("\n".join(lines))
            return

        if command.command == CommandName.delete:
            deleted = await service.delete_from_command(chat_id=message.chat.id, command=command)
            if deleted.deleted_count == 0:
                await message.answer("Подходящие напоминания не найдены, ничего не удалено.")
                return
            lines = [f"Удалено напоминаний: {deleted.deleted_count}"]
            for idx, item in enumerate(deleted.items, start=1):
                lines.append(f"{idx}. #{item.id} | {_format_run_at(item.run_at)}")
                lines.append(f"   {item.text}")
            await message.answer("\n".join(lines))
            return

    await message.answer("На текущем этапе эта команда еще не поддерживается.")


def create_router() -> Router:
    runtime_router = Router()
    runtime_router.message.register(on_text_message, F.text)
    return runtime_router
