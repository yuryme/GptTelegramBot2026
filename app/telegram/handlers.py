from uuid import uuid4
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

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

BTN_SHOW_TODAY = "Показать напоминания на сегодня"
BTN_SHOW_ALL = "Показать все напоминания"
BTN_SETTINGS = "Настройка"
BTN_MODELS = "Модели"
BTN_LIMITS = "Лимиты"
BTN_BACK = "Назад"
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
        "pending": "в ожидании",
        "done": "выполнено",
        "deleted": "удалено",
    }
    return mapping.get(status, status)


async def on_start_message(message: Message) -> None:
    await message.answer(
        "Выберите действие кнопкой ниже или отправьте запрос текстом.",
        reply_markup=_main_keyboard(),
    )


@router.message(F.text)
async def on_text_message(message: Message) -> None:
    if not message.text:
        await message.answer("Нужен текст запроса.")
        return

    text = message.text.strip()
    if text.startswith("/start"):
        await on_start_message(message)
        return
    text_lc = text.lower()
    if text == BTN_SETTINGS or text_lc.startswith("настрой"):
        await message.answer("Раздел настроек:", reply_markup=_settings_keyboard())
        return
    if text == BTN_BACK or text_lc == "назад":
        _chat_model_choices.pop(message.chat.id, None)
        await message.answer("Главное меню:", reply_markup=_main_keyboard())
        return
    if text == BTN_MODELS or text_lc.startswith("модел"):
        models = await llm_service.list_accessible_models()
        _chat_model_choices[message.chat.id] = {model: model for model in models}
        lines = ["Доступные модели для вашего ключа:"]
        for model in models[:MAX_MODEL_BUTTONS]:
            price = llm_service.get_model_price_per_1m(model)
            if price is None:
                lines.append(f"- {model}: цена за 1M токенов не указана")
            else:
                lines.append(f"- {model}: input ${price[0]:.2f}/1M, output ${price[1]:.2f}/1M")
        lines.append(f"Текущая модель: {llm_service.active_model}")
        await message.answer(
            "\n".join(lines),
            reply_markup=_models_keyboard(models),
        )
        return
    if text == BTN_LIMITS or text_lc.startswith("лимит"):
        account_snapshot = await llm_service.get_account_limit_snapshot()
        if account_snapshot is not None:
            await message.answer(
                "\n".join(
                    [
                        f"Лимит API-аккаунта: ${account_snapshot['hard_limit_usd']:.2f}",
                        f"Потрачено в этом месяце: ${account_snapshot['spent_usd']:.2f}",
                        f"Остаток лимита: ${account_snapshot['remaining_usd']:.2f}",
                        "",
                        f"Локальный лимит бота: ${settings.openai_monthly_budget_usd:.2f}",
                    ]
                ),
                reply_markup=_settings_keyboard(),
            )
            return
        await message.answer(
            "\n".join(
                [
                    f"Месячный лимит: ${settings.openai_monthly_budget_usd}",
                    f"Оценка входа за 1K токенов: ${settings.openai_estimated_input_cost_per_1k}",
                    f"Оценка выхода за 1K токенов: ${settings.openai_estimated_output_cost_per_1k}",
                    "API-лимит аккаунта недоступен для текущего ключа.",
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
            f"Активная модель изменена: {selected}",
            reply_markup=_settings_keyboard(),
        )
        return

    if not chat_rate_limiter.allow(message.chat.id):
        await message.answer("Слишком много запросов. Подождите немного и попробуйте снова.")
        return

    try:
        command = await llm_service.build_command(text)
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
            if not created:
                await message.answer("Напоминания не созданы.")
                return
            await service._repository.log_action(
                action_id=str(uuid4()),
                chat_id=message.chat.id,
                action_type="create",
                target_scope="multi" if len(created) > 1 else "single",
                source_text=text,
                parsed_command=command.model_dump(mode="json"),
                result_stats={"created": len(created), "matched": len(created), "changed": len(created)},
            )
            lines = ["Созданные напоминания:"]
            for idx, item in enumerate(created, start=1):
                lines.append(f"{idx}. #{item.id} | {_format_run_at(item.run_at)}")
                lines.append(f"   {item.text}")
            await message.answer("\n".join(lines))
            return

        if command.command == CommandName.list_items:
            items = await service.list_from_command(chat_id=message.chat.id, command=command)
            if not items:
                await message.answer("Напоминания не найдены.")
                return
            await service._repository.log_action(
                action_id=str(uuid4()),
                chat_id=message.chat.id,
                action_type="list",
                target_scope="multi",
                source_text=text,
                parsed_command=command.model_dump(mode="json"),
                result_stats={"matched": len(items), "created": 0, "changed": 0},
            )
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
            await service._repository.log_action(
                action_id=str(uuid4()),
                chat_id=message.chat.id,
                action_type="delete",
                target_scope="multi" if deleted.deleted_count > 1 else "single",
                source_text=text,
                parsed_command=command.model_dump(mode="json"),
                result_stats={"matched": len(deleted.items), "created": 0, "changed": deleted.deleted_count},
            )
            lines = [f"Удалено напоминаний: {deleted.deleted_count}"]
            for idx, item in enumerate(deleted.items, start=1):
                lines.append(f"{idx}. #{item.id} | {_format_run_at(item.run_at)}")
                lines.append(f"   {item.text}")
            await message.answer("\n".join(lines))
            return

    await message.answer("На текущем этапе эта команда еще не поддерживается.")


def create_router() -> Router:
    runtime_router = Router()
    runtime_router.message.register(on_start_message, CommandStart())
    runtime_router.message.register(on_text_message, F.text)
    return runtime_router
