from __future__ import annotations

import json
import logging
import re
from asyncio import sleep
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import ValidationError

from app.core.settings import get_settings
from app.llm.prompts import SYSTEM_PROMPT_RU
from app.schemas.commands import AssistantCommand, CommandName, assistant_command_adapter
from app.services.cost_control import MonthlyCostGuard
from app.services.guardrails import LLMCircuitBreaker


class LLMCommandValidationError(ValueError):
    pass


class LLMBudgetExceededError(ValueError):
    pass


class LLMRateLimitError(ValueError):
    pass


class LLMCircuitOpenError(ValueError):
    pass


logger = logging.getLogger(__name__)


class LLMService:
    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        cost_guard: MonthlyCostGuard | None = None,
        circuit_breaker: LLMCircuitBreaker | None = None,
    ) -> None:
        settings = get_settings()
        self._model = settings.openai_model
        self._client = client or AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0)
        self._cost_guard = cost_guard or MonthlyCostGuard(
            monthly_usd_limit=settings.openai_monthly_budget_usd,
            estimated_input_cost_per_1k=settings.openai_estimated_input_cost_per_1k,
            estimated_output_cost_per_1k=settings.openai_estimated_output_cost_per_1k,
        )
        self._circuit_breaker = circuit_breaker or LLMCircuitBreaker(
            failure_threshold=settings.llm_circuit_failure_threshold,
            open_seconds=settings.llm_circuit_open_seconds,
        )

    async def build_command(self, user_text: str, now: datetime | None = None) -> AssistantCommand:
        settings = get_settings()
        local_tz = ZoneInfo(settings.app_timezone)
        now = now or datetime.now(local_tz)
        if self._circuit_breaker.is_open(now):
            raise LLMCircuitOpenError("LLM circuit breaker is open")
        if not self._cost_guard.can_spend(estimated_usd=0.001, now=now):
            raise LLMBudgetExceededError("Monthly LLM budget exceeded")

        response = None
        for attempt in range(2):
            try:
                response = await self._client.responses.create(
                    model=self._model,
                    input=[
                        {"role": "system", "content": SYSTEM_PROMPT_RU},
                        {
                            "role": "user",
                            "content": (
                                "Пользовательский запрос: "
                                f"{user_text}\n"
                                f"Текущее локальное время ({settings.app_timezone}): {now.isoformat()}\n"
                                "Интерпретируй время пользователя в этом часовом поясе.\n"
                                "Верни только JSON команды."
                            ),
                        },
                    ],
                    temperature=0,
                )
                break
            except RateLimitError as exc:
                self._circuit_breaker.register_failure(now)
                raise LLMRateLimitError("OpenAI rate limit or quota exceeded") from exc
            except (APIConnectionError, APITimeoutError):
                if attempt == 1:
                    raise
                await sleep(0.5 * (attempt + 1))

        assert response is not None
        self._circuit_breaker.register_success()
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        snapshot = self._cost_guard.register_tokens(input_tokens, output_tokens, now=now)
        logger.info(
            "LLM usage tracked: month=%s total_tokens=%s total_usd=%.6f",
            snapshot.month_key,
            snapshot.total_tokens,
            snapshot.total_usd,
        )
        for threshold in self._cost_guard.get_new_alert_thresholds(now):
            logger.warning("LLM budget threshold reached: %s%%", threshold)
        raw_output = (response.output_text or "").strip()
        logger.info("LLM raw output: %s", raw_output)
        command = parse_assistant_command(raw_output)
        return _enforce_explicit_filters(user_text=user_text, command=command, now=now)


def parse_assistant_command(raw_output: str | dict[str, Any]) -> AssistantCommand:
    payload: dict[str, Any]
    if isinstance(raw_output, str):
        cleaned = _normalize_llm_json_text(raw_output)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMCommandValidationError("LLM output is not valid JSON") from exc
    else:
        payload = raw_output

    try:
        return assistant_command_adapter.validate_python(payload)
    except ValidationError as exc:
        logger.warning("LLM schema validation failed. payload=%s errors=%s", payload, exc.errors())
        raise LLMCommandValidationError("LLM command does not match schema") from exc


def _normalize_llm_json_text(text: str) -> str:
    value = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", value, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        value = fenced.group(1).strip()
    return value


def _extract_search_text_hint(user_text: str) -> str | None:
    text = user_text.strip()
    patterns = [
        r"(?:где\s+упомина(?:ется|ются)|где\s+есть|содержит|по\s+слову)\s+[\"«]?([^\"»]+?)[\"»]?(?:[?.!,]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).strip()
        if value:
            return value
    return None


def _enforce_explicit_filters(user_text: str, command: AssistantCommand, now: datetime) -> AssistantCommand:
    if command.command != CommandName.list_items:
        return command
    date_range = _extract_date_range_hint(user_text=user_text, now=now)
    if date_range and command.from_dt is None and command.to_dt is None:
        command = command.model_copy(
            update={"mode": "range", "from_dt": date_range[0], "to_dt": date_range[1]}
        )
    search_hint = _extract_search_text_hint(user_text)
    if not search_hint or command.search_text:
        return command
    update: dict[str, Any] = {"search_text": search_hint}
    if command.mode != "range":
        update["mode"] = "search"
    return command.model_copy(update=update)


def _extract_date_range_hint(user_text: str, now: datetime) -> tuple[datetime, datetime] | None:
    text = user_text.strip().lower()
    month_map = {
        "января": 1,
        "февраля": 2,
        "марта": 3,
        "апреля": 4,
        "мая": 5,
        "июня": 6,
        "июля": 7,
        "августа": 8,
        "сентября": 9,
        "октября": 10,
        "ноября": 11,
        "декабря": 12,
    }

    def day_bounds(year: int, month: int, day: int, *, roll_year_if_past: bool) -> tuple[datetime, datetime] | None:
        try:
            day_start = datetime(year, month, day, 0, 0, 0, 0, tzinfo=now.tzinfo)
            if roll_year_if_past and day_start.date() < now.date():
                day_start = datetime(year + 1, month, day, 0, 0, 0, 0, tzinfo=now.tzinfo)
            return day_start, day_start + timedelta(days=1) - timedelta(microseconds=1)
        except ValueError:
            return None

    # относительные периоды
    if "сегодня" in text:
        return day_bounds(now.year, now.month, now.day, roll_year_if_past=False)
    if "послезавтра" in text:
        target = now + timedelta(days=2)
        return day_bounds(target.year, target.month, target.day, roll_year_if_past=False)
    if "завтра" in text:
        target = now + timedelta(days=1)
        return day_bounds(target.year, target.month, target.day, roll_year_if_past=False)

    if "на этой неделе" in text:
        start = datetime.combine((now - timedelta(days=now.weekday())).date(), datetime.min.time(), tzinfo=now.tzinfo)
        return start, start + timedelta(days=7) - timedelta(microseconds=1)
    if "на следующей неделе" in text:
        start = datetime.combine((now - timedelta(days=now.weekday()) + timedelta(days=7)).date(), datetime.min.time(), tzinfo=now.tzinfo)
        return start, start + timedelta(days=7) - timedelta(microseconds=1)

    if "в этом месяце" in text:
        start = datetime(now.year, now.month, 1, tzinfo=now.tzinfo)
        next_month = datetime(now.year + (1 if now.month == 12 else 0), 1 if now.month == 12 else now.month + 1, 1, tzinfo=now.tzinfo)
        return start, next_month - timedelta(microseconds=1)
    if "в следующем месяце" in text:
        year = now.year + (1 if now.month == 12 else 0)
        month = 1 if now.month == 12 else now.month + 1
        start = datetime(year, month, 1, tzinfo=now.tzinfo)
        next_month = datetime(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1, tzinfo=now.tzinfo)
        return start, next_month - timedelta(microseconds=1)

    # "в диапазоне 24-26 февраля", "24 - 26 февраля", "с 24 по 26 февраля"
    m = re.search(
        r"(?:в\s+диапазоне\s+|с\s+)?(\d{1,2})\s*(?:-|–|—|по|до|и)\s*(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?\b",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        d1 = int(m.group(1))
        d2 = int(m.group(2))
        month = month_map.get(m.group(3).lower())
        year = int(m.group(4)) if m.group(4) else now.year
        if month:
            left = day_bounds(year, month, min(d1, d2), roll_year_if_past=m.group(4) is None)
            right = day_bounds(year, month, max(d1, d2), roll_year_if_past=m.group(4) is None)
            if left and right:
                return left[0], right[1]

    # "с 24 февраля по 26 февраля"
    m = re.search(
        r"с\s+(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?\s+по\s+(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?\b",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        d1, d2 = int(m.group(1)), int(m.group(4))
        m1, m2 = month_map.get(m.group(2).lower()), month_map.get(m.group(5).lower())
        y1 = int(m.group(3)) if m.group(3) else now.year
        y2 = int(m.group(6)) if m.group(6) else y1
        if m1 and m2:
            left = day_bounds(y1, m1, d1, roll_year_if_past=m.group(3) is None)
            right = day_bounds(y2, m2, d2, roll_year_if_past=m.group(6) is None)
            if left and right:
                return left[0], right[1]

    # "на 24 февраля" / "на 24 февраля 2026"
    m = re.search(r"\bна\s+(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?\b", text, flags=re.IGNORECASE)
    if m:
        day = int(m.group(1))
        month = month_map.get(m.group(2).lower())
        year = int(m.group(3)) if m.group(3) else now.year
        if month:
            return day_bounds(year, month, day, roll_year_if_past=m.group(3) is None)

    # "на 24.02" / "на 24.02.2026", "с 24.02 по 26.02"
    m = re.search(r"\bс\s+(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\s+по\s+(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b", text)
    if m:
        y1 = int(m.group(3)) if m.group(3) else now.year
        y2 = int(m.group(6)) if m.group(6) else y1
        left = day_bounds(y1, int(m.group(2)), int(m.group(1)), roll_year_if_past=m.group(3) is None)
        right = day_bounds(y2, int(m.group(5)), int(m.group(4)), roll_year_if_past=m.group(6) is None)
        if left and right:
            return left[0], right[1]

    m = re.search(r"\bна\s+(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b", text, flags=re.IGNORECASE)
    if m:
        year = int(m.group(3)) if m.group(3) else now.year
        return day_bounds(year, int(m.group(2)), int(m.group(1)), roll_year_if_past=m.group(3) is None)

    return None
