from __future__ import annotations

import json
import logging
import re
from asyncio import sleep
from datetime import datetime, timezone
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

        raw_output = await self._request_primary_command(user_text=user_text, now=now)
        try:
            command = parse_assistant_command(raw_output)
        except LLMCommandValidationError:
            recovered = await self._recover_command_json_with_llm(user_text=user_text, raw_output=raw_output, now=now)
            if recovered is None:
                raise
            command = recovered

        if self._should_refine_list_command(command):
            refined = await self._refine_list_command_with_llm(user_text=user_text, command=command, now=now)
            if refined is not None:
                command = refined
        if command.command == CommandName.list_items and command.search_text:
            normalized_search = await self._normalize_search_text_with_llm(
                user_text=user_text,
                current_search_text=command.search_text,
                now=now,
            )
            if normalized_search:
                command = command.model_copy(update={"search_text": normalized_search})

        return command

    async def _request_primary_command(self, *, user_text: str, now: datetime) -> str:
        settings = get_settings()
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
        return raw_output

    def _should_refine_list_command(self, command: AssistantCommand) -> bool:
        if command.command != CommandName.list_items:
            return False
        if command.mode != "all":
            return False
        return command.search_text is None and command.from_dt is None and command.to_dt is None and command.status is None

    async def _refine_list_command_with_llm(
        self,
        *,
        user_text: str,
        command: AssistantCommand,
        now: datetime,
    ) -> AssistantCommand | None:
        settings = get_settings()
        prompt = (
            "Ты уточняешь команду list_reminders по естественному тексту пользователя. "
            "Верни только валидный JSON команды list_reminders в одной из форм mode: "
            "all/today/status/search/range. "
            "Если в тексте есть фильтр по слову, заполни search_text. "
            "Если в тексте есть период или дата, заполни from_dt/to_dt и mode=range. "
            "Не выдумывай фильтры, которых нет в тексте."
        )
        base_json = json.dumps(command.model_dump(mode="json"), ensure_ascii=False)
        try:
            response = await self._client.responses.create(
                model=self._model,
                input=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Пользовательский запрос: {user_text}\n"
                            f"Текущее локальное время ({settings.app_timezone}): {now.isoformat()}\n"
                            f"Текущая команда: {base_json}"
                        ),
                    },
                ],
                temperature=0,
            )
        except Exception:
            logger.exception("Failed to refine list command with LLM")
            return None

        refined_raw = (response.output_text or "").strip()
        logger.info("LLM refined list raw output: %s", refined_raw)
        try:
            refined = parse_assistant_command(refined_raw)
        except LLMCommandValidationError:
            logger.warning("Refined list output is invalid: %s", refined_raw)
            return None

        if refined.command != CommandName.list_items:
            logger.warning("Refined command has unexpected type: %s", refined.command)
            return None
        return refined

    async def _recover_command_json_with_llm(
        self,
        *,
        user_text: str,
        raw_output: str,
        now: datetime,
    ) -> AssistantCommand | None:
        settings = get_settings()
        prompt = (
            "Исправь ответ модели в строго валидный JSON команды для схемы AssistantCommand. "
            "Разрешенные command: create_reminders, list_reminders, delete_reminders. "
            "Никакого markdown, только JSON."
        )
        try:
            response = await self._client.responses.create(
                model=self._model,
                input=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Пользовательский запрос: {user_text}\n"
                            f"Текущее локальное время ({settings.app_timezone}): {now.isoformat()}\n"
                            f"Невалидный ответ модели: {raw_output}"
                        ),
                    },
                ],
                temperature=0,
            )
        except Exception:
            logger.exception("Failed to recover invalid command JSON with LLM")
            return None

        fixed_output = (response.output_text or "").strip()
        logger.info("LLM recovered raw output: %s", fixed_output)
        try:
            return parse_assistant_command(fixed_output)
        except LLMCommandValidationError:
            logger.warning("Recovered output is still invalid: %s", fixed_output)
            return None

    async def _normalize_search_text_with_llm(
        self,
        *,
        user_text: str,
        current_search_text: str,
        now: datetime,
    ) -> str | None:
        settings = get_settings()
        prompt = (
            "Ты нормализуешь search_text для поиска напоминаний. "
            "Верни только JSON: {\"search_text\":\"...\"}. "
            "Задача: вернуть короткую основу (стем) 4-8 символов, чтобы один поиск покрывал словоформы "
            "(например, Сергей/Сергея/Сергеем -> серге). "
            "Возвращай только основу в нижнем регистре, без пробелов и без лишних слов."
        )
        try:
            response = await self._client.responses.create(
                model=self._model,
                input=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Пользовательский запрос: {user_text}\n"
                            f"Текущее локальное время ({settings.app_timezone}): {now.isoformat()}\n"
                            f"Текущий search_text: {current_search_text}"
                        ),
                    },
                ],
                temperature=0,
            )
        except Exception:
            logger.exception("Failed to normalize search_text with LLM")
            return None

        raw = (response.output_text or "").strip()
        logger.info("LLM search normalize raw output: %s", raw)
        try:
            payload = json.loads(_normalize_llm_json_text(raw))
            value = str(payload.get("search_text", "")).strip().lower()
            return value or None
        except Exception:
            logger.warning("Invalid search normalize JSON: %s", raw)
            return None


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
    payload = _normalize_legacy_command_payload(payload)

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


def _normalize_legacy_command_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if normalized.get("command") == "delete_reminders":
        if "status" not in normalized and "filter_status" in normalized:
            normalized["status"] = normalized.get("filter_status")
    return normalized
