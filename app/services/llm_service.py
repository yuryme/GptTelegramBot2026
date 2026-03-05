from __future__ import annotations

import json
import logging
import re
from asyncio import sleep
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import ValidationError

from app.core.settings import get_settings
from app.llm.prompts import SYSTEM_PROMPT_RU
from app.schemas.commands import AssistantCommand, CommandName, DayReference, assistant_command_adapter
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
        self._api_key = settings.openai_api_key
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
        self._known_model_prices_per_1m: dict[str, tuple[float, float]] = {
            # input, output USD per 1M tokens (static reference catalog)
            "gpt-4.1": (2.0, 8.0),
            "gpt-4.1-mini": (0.4, 1.6),
            "gpt-4.1-nano": (0.1, 0.4),
            "gpt-4o": (5.0, 15.0),
            "gpt-4o-mini": (0.15, 0.6),
            "o4-mini": (1.1, 4.4),
            "o3-mini": (1.1, 4.4),
            # Legacy GPT-4 / GPT-4 Turbo
            "gpt-4": (30.0, 60.0),
            "gpt-4-0613": (30.0, 60.0),
            "gpt-4-0125-preview": (10.0, 30.0),
            "gpt-4-1106-preview": (10.0, 30.0),
            "gpt-4-turbo": (10.0, 30.0),
            "gpt-4-turbo-preview": (10.0, 30.0),
            "gpt-4-turbo-2024-04-09": (10.0, 30.0),
            # Legacy GPT-3.5
            "gpt-3.5-turbo": (0.5, 1.5),
            "gpt-3.5-turbo-0125": (0.5, 1.5),
            "gpt-3.5-turbo-1106": (1.0, 2.0),
            "gpt-3.5-turbo-16k": (3.0, 4.0),
            "gpt-3.5-turbo-instruct": (1.5, 1.5),
            "gpt-3.5-turbo-instruct-0914": (1.5, 1.5),
        }

    @property
    def active_model(self) -> str:
        return self._model

    def set_active_model(self, model: str) -> None:
        self._model = model.strip()

    async def list_accessible_models(self) -> list[str]:
        try:
            result = await self._client.models.list()
        except Exception:
            logger.exception("Failed to fetch available OpenAI models")
            return [self._model]

        model_ids = sorted(
            {
                item.id
                for item in getattr(result, "data", [])
                if isinstance(getattr(item, "id", None), str)
                and (item.id.startswith("gpt-") or item.id.startswith("o"))
            }
        )
        if not model_ids:
            return [self._model]
        if self._model not in model_ids:
            model_ids.insert(0, self._model)
        return model_ids

    def get_model_price_per_1m(self, model: str) -> tuple[float, float] | None:
        direct = self._known_model_prices_per_1m.get(model)
        if direct is not None:
            return direct

        # Fallbacks for versioned/alias model IDs returned by models.list()
        if model.startswith("gpt-4-turbo"):
            return self._known_model_prices_per_1m.get("gpt-4-turbo")
        if model.startswith("gpt-4-0125") or model.startswith("gpt-4-1106"):
            return self._known_model_prices_per_1m.get("gpt-4-1106-preview")
        if model.startswith("gpt-4-"):
            return self._known_model_prices_per_1m.get("gpt-4")

        if model.startswith("gpt-3.5-turbo-instruct"):
            return self._known_model_prices_per_1m.get("gpt-3.5-turbo-instruct")
        if model.startswith("gpt-3.5-turbo-16k"):
            return self._known_model_prices_per_1m.get("gpt-3.5-turbo-16k")
        if model.startswith("gpt-3.5-turbo"):
            return self._known_model_prices_per_1m.get("gpt-3.5-turbo")

        return None

    async def get_account_limit_snapshot(self) -> dict[str, float] | None:
        if not self._api_key:
            return None
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_date = month_start.strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                sub_resp = await client.get(
                    "https://api.openai.com/dashboard/billing/subscription",
                    headers=headers,
                )
                usage_resp = await client.get(
                    "https://api.openai.com/dashboard/billing/usage",
                    headers=headers,
                    params={"start_date": start_date, "end_date": end_date},
                )
            if sub_resp.status_code != 200 or usage_resp.status_code != 200:
                return None
            sub_payload = sub_resp.json()
            usage_payload = usage_resp.json()
            hard_limit_usd = float(sub_payload.get("hard_limit_usd", 0.0) or 0.0)
            total_usage_cents = float(usage_payload.get("total_usage", 0.0) or 0.0)
            spent_usd = total_usage_cents / 100.0
            remaining_usd = max(0.0, hard_limit_usd - spent_usd)
            return {
                "hard_limit_usd": hard_limit_usd,
                "spent_usd": spent_usd,
                "remaining_usd": remaining_usd,
            }
        except Exception:
            logger.exception("Failed to fetch account billing snapshot")
            return None

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

        command = self._repair_create_command_dates(command=command, user_text=user_text)

        # Fast path: skip extra refinement/normalization LLM round-trips.
        # This keeps latency predictable by relying on the primary parsed command.

        return command

    def _repair_create_command_dates(self, *, command: AssistantCommand, user_text: str) -> AssistantCommand:
        if command.command != CommandName.create:
            return command

        text = user_text.lower()
        inferred_day_ref: DayReference | None = None
        if "послезавтра" in text:
            inferred_day_ref = DayReference.day_after_tomorrow
        elif "завтра" in text:
            inferred_day_ref = DayReference.tomorrow
        elif "сегодня" in text:
            inferred_day_ref = DayReference.today

        if inferred_day_ref is None:
            return command

        changed = False
        fixed_reminders = []
        for item in command.reminders:
            if item.day_reference is not None or item.run_at is None:
                fixed_reminders.append(item)
                continue

            run_at_value = item.run_at
            hhmm = run_at_value.strftime("%H:%M")
            fixed = item.model_copy(
                update={
                    "run_at": None,
                    "day_reference": inferred_day_ref,
                    "time_value": hhmm,
                    "explicit_time_provided": True,
                }
            )
            fixed_reminders.append(fixed)
            changed = True

        if not changed:
            return command

        return command.model_copy(update={"reminders": fixed_reminders})

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
                                "Р В РЎСџР В РЎвЂўР В Р’В»Р РЋР Р‰Р В Р’В·Р В РЎвЂўР В Р вЂ Р В Р’В°Р РЋРІР‚С™Р В Р’ВµР В Р’В»Р РЋР Р‰Р РЋР С“Р В РЎвЂќР В РЎвЂР В РІвЂћвЂ“ Р В Р’В·Р В Р’В°Р В РЎвЂ”Р РЋР вЂљР В РЎвЂўР РЋР С“: "
                                f"{user_text}\n"
                                f"Р В РЎС›Р В Р’ВµР В РЎвЂќР РЋРЎвЂњР РЋРІР‚В°Р В Р’ВµР В Р’Вµ Р В Р’В»Р В РЎвЂўР В РЎвЂќР В Р’В°Р В Р’В»Р РЋР Р‰Р В Р вЂ¦Р В РЎвЂўР В Р’Вµ Р В Р вЂ Р РЋР вЂљР В Р’ВµР В РЎВР РЋР РЏ ({settings.app_timezone}): {now.isoformat()}\n"
                                "Р В Р’ВР В Р вЂ¦Р РЋРІР‚С™Р В Р’ВµР РЋР вЂљР В РЎвЂ”Р РЋР вЂљР В Р’ВµР РЋРІР‚С™Р В РЎвЂР РЋР вЂљР РЋРЎвЂњР В РІвЂћвЂ“ Р В Р вЂ Р РЋР вЂљР В Р’ВµР В РЎВР РЋР РЏ Р В РЎвЂ”Р В РЎвЂўР В Р’В»Р РЋР Р‰Р В Р’В·Р В РЎвЂўР В Р вЂ Р В Р’В°Р РЋРІР‚С™Р В Р’ВµР В Р’В»Р РЋР РЏ Р В Р вЂ  Р РЋР РЉР РЋРІР‚С™Р В РЎвЂўР В РЎВ Р РЋРІР‚РЋР В Р’В°Р РЋР С“Р В РЎвЂўР В Р вЂ Р В РЎвЂўР В РЎВ Р В РЎвЂ”Р В РЎвЂўР РЋР РЏР РЋР С“Р В Р’Вµ.\n"
                                "Р В РІР‚в„ўР В Р’ВµР РЋР вЂљР В Р вЂ¦Р В РЎвЂ Р РЋРІР‚С™Р В РЎвЂўР В Р’В»Р РЋР Р‰Р В РЎвЂќР В РЎвЂў JSON Р В РЎвЂќР В РЎвЂўР В РЎВР В Р’В°Р В Р вЂ¦Р В РўвЂР РЋРІР‚в„–."
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

    def _should_refine_list_command(self, *, command: AssistantCommand, user_text: str) -> bool:
        if command.command != CommandName.list_items:
            return False
        if command.mode != "all":
            return False
        if not (
            command.search_text is None
            and command.from_dt is None
            and command.to_dt is None
            and command.status is None
        ):
            return False

        # Avoid extra LLM round-trip for simple "show all" requests.
        text = user_text.lower()
        refine_hints = (
            "сегодня",
            "завтра",
            "послезавтра",
            "вчера",
            "на неделе",
            "на этой неделе",
            "в этом месяце",
            "между",
            "с ",
            "по ",
            "до ",
            "после ",
            "диапазон",
            "содерж",
            "найди",
            "поиск",
        )
        return any(hint in text for hint in refine_hints)

    async def _refine_list_command_with_llm(
        self,
        *,
        user_text: str,
        command: AssistantCommand,
        now: datetime,
    ) -> AssistantCommand | None:
        settings = get_settings()
        prompt = (
            "Р В РЎС›Р РЋРІР‚в„– Р РЋРЎвЂњР РЋРІР‚С™Р В РЎвЂўР РЋРІР‚РЋР В Р вЂ¦Р РЋР РЏР В Р’ВµР РЋРІвЂљВ¬Р РЋР Р‰ Р В РЎвЂќР В РЎвЂўР В РЎВР В Р’В°Р В Р вЂ¦Р В РўвЂР РЋРЎвЂњ list_reminders Р В РЎвЂ”Р В РЎвЂў Р В Р’ВµР РЋР С“Р РЋРІР‚С™Р В Р’ВµР РЋР С“Р РЋРІР‚С™Р В Р вЂ Р В Р’ВµР В Р вЂ¦Р В Р вЂ¦Р В РЎвЂўР В РЎВР РЋРЎвЂњ Р РЋРІР‚С™Р В Р’ВµР В РЎвЂќР РЋР С“Р РЋРІР‚С™Р РЋРЎвЂњ Р В РЎвЂ”Р В РЎвЂўР В Р’В»Р РЋР Р‰Р В Р’В·Р В РЎвЂўР В Р вЂ Р В Р’В°Р РЋРІР‚С™Р В Р’ВµР В Р’В»Р РЋР РЏ. "
            "Р В РІР‚в„ўР В Р’ВµР РЋР вЂљР В Р вЂ¦Р В РЎвЂ Р РЋРІР‚С™Р В РЎвЂўР В Р’В»Р РЋР Р‰Р В РЎвЂќР В РЎвЂў Р В Р вЂ Р В Р’В°Р В Р’В»Р В РЎвЂР В РўвЂР В Р вЂ¦Р РЋРІР‚в„–Р В РІвЂћвЂ“ JSON Р В РЎвЂќР В РЎвЂўР В РЎВР В Р’В°Р В Р вЂ¦Р В РўвЂР РЋРІР‚в„– list_reminders Р В Р вЂ  Р В РЎвЂўР В РўвЂР В Р вЂ¦Р В РЎвЂўР В РІвЂћвЂ“ Р В РЎвЂР В Р’В· Р РЋРІР‚С›Р В РЎвЂўР РЋР вЂљР В РЎВ mode: "
            "all/today/status/search/range. "
            "Р В РІР‚СћР РЋР С“Р В Р’В»Р В РЎвЂ Р В Р вЂ  Р РЋРІР‚С™Р В Р’ВµР В РЎвЂќР РЋР С“Р РЋРІР‚С™Р В Р’Вµ Р В Р’ВµР РЋР С“Р РЋРІР‚С™Р РЋР Р‰ Р РЋРІР‚С›Р В РЎвЂР В Р’В»Р РЋР Р‰Р РЋРІР‚С™Р РЋР вЂљ Р В РЎвЂ”Р В РЎвЂў Р РЋР С“Р В Р’В»Р В РЎвЂўР В Р вЂ Р РЋРЎвЂњ, Р В Р’В·Р В Р’В°Р В РЎвЂ”Р В РЎвЂўР В Р’В»Р В Р вЂ¦Р В РЎвЂ search_text. "
            "Р В РІР‚СћР РЋР С“Р В Р’В»Р В РЎвЂ Р В Р вЂ  Р РЋРІР‚С™Р В Р’ВµР В РЎвЂќР РЋР С“Р РЋРІР‚С™Р В Р’Вµ Р В Р’ВµР РЋР С“Р РЋРІР‚С™Р РЋР Р‰ Р В РЎвЂ”Р В Р’ВµР РЋР вЂљР В РЎвЂР В РЎвЂўР В РўвЂ Р В РЎвЂР В Р’В»Р В РЎвЂ Р В РўвЂР В Р’В°Р РЋРІР‚С™Р В Р’В°, Р В Р’В·Р В Р’В°Р В РЎвЂ”Р В РЎвЂўР В Р’В»Р В Р вЂ¦Р В РЎвЂ from_dt/to_dt Р В РЎвЂ mode=range. "
            "Р В РЎСљР В Р’Вµ Р В Р вЂ Р РЋРІР‚в„–Р В РўвЂР РЋРЎвЂњР В РЎВР РЋРІР‚в„–Р В Р вЂ Р В Р’В°Р В РІвЂћвЂ“ Р РЋРІР‚С›Р В РЎвЂР В Р’В»Р РЋР Р‰Р РЋРІР‚С™Р РЋР вЂљР РЋРІР‚в„–, Р В РЎвЂќР В РЎвЂўР РЋРІР‚С™Р В РЎвЂўР РЋР вЂљР РЋРІР‚в„–Р РЋРІР‚В¦ Р В Р вЂ¦Р В Р’ВµР РЋРІР‚С™ Р В Р вЂ  Р РЋРІР‚С™Р В Р’ВµР В РЎвЂќР РЋР С“Р РЋРІР‚С™Р В Р’Вµ."
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
                            f"Р В РЎСџР В РЎвЂўР В Р’В»Р РЋР Р‰Р В Р’В·Р В РЎвЂўР В Р вЂ Р В Р’В°Р РЋРІР‚С™Р В Р’ВµР В Р’В»Р РЋР Р‰Р РЋР С“Р В РЎвЂќР В РЎвЂР В РІвЂћвЂ“ Р В Р’В·Р В Р’В°Р В РЎвЂ”Р РЋР вЂљР В РЎвЂўР РЋР С“: {user_text}\n"
                            f"Р В РЎС›Р В Р’ВµР В РЎвЂќР РЋРЎвЂњР РЋРІР‚В°Р В Р’ВµР В Р’Вµ Р В Р’В»Р В РЎвЂўР В РЎвЂќР В Р’В°Р В Р’В»Р РЋР Р‰Р В Р вЂ¦Р В РЎвЂўР В Р’Вµ Р В Р вЂ Р РЋР вЂљР В Р’ВµР В РЎВР РЋР РЏ ({settings.app_timezone}): {now.isoformat()}\n"
                            f"Р В РЎС›Р В Р’ВµР В РЎвЂќР РЋРЎвЂњР РЋРІР‚В°Р В Р’В°Р РЋР РЏ Р В РЎвЂќР В РЎвЂўР В РЎВР В Р’В°Р В Р вЂ¦Р В РўвЂР В Р’В°: {base_json}"
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
            "Р В Р’ВР РЋР С“Р В РЎвЂ”Р РЋР вЂљР В Р’В°Р В Р вЂ Р РЋР Р‰ Р В РЎвЂўР РЋРІР‚С™Р В Р вЂ Р В Р’ВµР РЋРІР‚С™ Р В РЎВР В РЎвЂўР В РўвЂР В Р’ВµР В Р’В»Р В РЎвЂ Р В Р вЂ  Р РЋР С“Р РЋРІР‚С™Р РЋР вЂљР В РЎвЂўР В РЎвЂ“Р В РЎвЂў Р В Р вЂ Р В Р’В°Р В Р’В»Р В РЎвЂР В РўвЂР В Р вЂ¦Р РЋРІР‚в„–Р В РІвЂћвЂ“ JSON Р В РЎвЂќР В РЎвЂўР В РЎВР В Р’В°Р В Р вЂ¦Р В РўвЂР РЋРІР‚в„– Р В РўвЂР В Р’В»Р РЋР РЏ Р РЋР С“Р РЋРІР‚В¦Р В Р’ВµР В РЎВР РЋРІР‚в„– AssistantCommand. "
            "Р В Р’В Р В Р’В°Р В Р’В·Р РЋР вЂљР В Р’ВµР РЋРІвЂљВ¬Р В Р’ВµР В Р вЂ¦Р В Р вЂ¦Р РЋРІР‚в„–Р В Р’Вµ command: create_reminders, list_reminders, delete_reminders. "
            "Р В РЎСљР В РЎвЂР В РЎвЂќР В Р’В°Р В РЎвЂќР В РЎвЂўР В РЎвЂ“Р В РЎвЂў markdown, Р РЋРІР‚С™Р В РЎвЂўР В Р’В»Р РЋР Р‰Р В РЎвЂќР В РЎвЂў JSON."
        )
        try:
            response = await self._client.responses.create(
                model=self._model,
                input=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Р В РЎСџР В РЎвЂўР В Р’В»Р РЋР Р‰Р В Р’В·Р В РЎвЂўР В Р вЂ Р В Р’В°Р РЋРІР‚С™Р В Р’ВµР В Р’В»Р РЋР Р‰Р РЋР С“Р В РЎвЂќР В РЎвЂР В РІвЂћвЂ“ Р В Р’В·Р В Р’В°Р В РЎвЂ”Р РЋР вЂљР В РЎвЂўР РЋР С“: {user_text}\n"
                            f"Р В РЎС›Р В Р’ВµР В РЎвЂќР РЋРЎвЂњР РЋРІР‚В°Р В Р’ВµР В Р’Вµ Р В Р’В»Р В РЎвЂўР В РЎвЂќР В Р’В°Р В Р’В»Р РЋР Р‰Р В Р вЂ¦Р В РЎвЂўР В Р’Вµ Р В Р вЂ Р РЋР вЂљР В Р’ВµР В РЎВР РЋР РЏ ({settings.app_timezone}): {now.isoformat()}\n"
                            f"Р В РЎСљР В Р’ВµР В Р вЂ Р В Р’В°Р В Р’В»Р В РЎвЂР В РўвЂР В Р вЂ¦Р РЋРІР‚в„–Р В РІвЂћвЂ“ Р В РЎвЂўР РЋРІР‚С™Р В Р вЂ Р В Р’ВµР РЋРІР‚С™ Р В РЎВР В РЎвЂўР В РўвЂР В Р’ВµР В Р’В»Р В РЎвЂ: {raw_output}"
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
            "Р В РЎС›Р РЋРІР‚в„– Р В Р вЂ¦Р В РЎвЂўР РЋР вЂљР В РЎВР В Р’В°Р В Р’В»Р В РЎвЂР В Р’В·Р РЋРЎвЂњР В Р’ВµР РЋРІвЂљВ¬Р РЋР Р‰ search_text Р В РўвЂР В Р’В»Р РЋР РЏ Р В РЎвЂ”Р В РЎвЂўР В РЎвЂР РЋР С“Р В РЎвЂќР В Р’В° Р В Р вЂ¦Р В Р’В°Р В РЎвЂ”Р В РЎвЂўР В РЎВР В РЎвЂР В Р вЂ¦Р В Р’В°Р В Р вЂ¦Р В РЎвЂР В РІвЂћвЂ“. "
            "Р В РІР‚в„ўР В Р’ВµР РЋР вЂљР В Р вЂ¦Р В РЎвЂ Р РЋРІР‚С™Р В РЎвЂўР В Р’В»Р РЋР Р‰Р В РЎвЂќР В РЎвЂў JSON: {\"search_text\":\"...\"}. "
            "Р В РІР‚вЂќР В Р’В°Р В РўвЂР В Р’В°Р РЋРІР‚РЋР В Р’В°: Р В Р вЂ Р В Р’ВµР РЋР вЂљР В Р вЂ¦Р РЋРЎвЂњР РЋРІР‚С™Р РЋР Р‰ Р В РЎвЂќР В РЎвЂўР РЋР вЂљР В РЎвЂўР РЋРІР‚С™Р В РЎвЂќР РЋРЎвЂњР РЋР вЂ№ Р В РЎвЂўР РЋР С“Р В Р вЂ¦Р В РЎвЂўР В Р вЂ Р РЋРЎвЂњ (Р РЋР С“Р РЋРІР‚С™Р В Р’ВµР В РЎВ) 4-8 Р РЋР С“Р В РЎвЂР В РЎВР В Р вЂ Р В РЎвЂўР В Р’В»Р В РЎвЂўР В Р вЂ , Р РЋРІР‚РЋР РЋРІР‚С™Р В РЎвЂўР В Р’В±Р РЋРІР‚в„– Р В РЎвЂўР В РўвЂР В РЎвЂР В Р вЂ¦ Р В РЎвЂ”Р В РЎвЂўР В РЎвЂР РЋР С“Р В РЎвЂќ Р В РЎвЂ”Р В РЎвЂўР В РЎвЂќР РЋР вЂљР РЋРІР‚в„–Р В Р вЂ Р В Р’В°Р В Р’В» Р РЋР С“Р В Р’В»Р В РЎвЂўР В Р вЂ Р В РЎвЂўР РЋРІР‚С›Р В РЎвЂўР РЋР вЂљР В РЎВР РЋРІР‚в„– "
            "(Р В Р вЂ¦Р В Р’В°Р В РЎвЂ”Р РЋР вЂљР В РЎвЂР В РЎВР В Р’ВµР РЋР вЂљ, Р В Р Р‹Р В Р’ВµР РЋР вЂљР В РЎвЂ“Р В Р’ВµР В РІвЂћвЂ“/Р В Р Р‹Р В Р’ВµР РЋР вЂљР В РЎвЂ“Р В Р’ВµР РЋР РЏ/Р В Р Р‹Р В Р’ВµР РЋР вЂљР В РЎвЂ“Р В Р’ВµР В Р’ВµР В РЎВ -> Р РЋР С“Р В Р’ВµР РЋР вЂљР В РЎвЂ“Р В Р’Вµ). "
            "Р В РІР‚в„ўР В РЎвЂўР В Р’В·Р В Р вЂ Р РЋР вЂљР В Р’В°Р РЋРІР‚В°Р В Р’В°Р В РІвЂћвЂ“ Р РЋРІР‚С™Р В РЎвЂўР В Р’В»Р РЋР Р‰Р В РЎвЂќР В РЎвЂў Р В РЎвЂўР РЋР С“Р В Р вЂ¦Р В РЎвЂўР В Р вЂ Р РЋРЎвЂњ Р В Р вЂ  Р В Р вЂ¦Р В РЎвЂР В Р’В¶Р В Р вЂ¦Р В Р’ВµР В РЎВ Р РЋР вЂљР В Р’ВµР В РЎвЂ“Р В РЎвЂР РЋР С“Р РЋРІР‚С™Р РЋР вЂљР В Р’Вµ, Р В Р’В±Р В Р’ВµР В Р’В· Р В РЎвЂ”Р РЋР вЂљР В РЎвЂўР В Р’В±Р В Р’ВµР В Р’В»Р В РЎвЂўР В Р вЂ  Р В РЎвЂ Р В Р’В±Р В Р’ВµР В Р’В· Р В Р’В»Р В РЎвЂР РЋРІвЂљВ¬Р В Р вЂ¦Р В РЎвЂР РЋРІР‚В¦ Р РЋР С“Р В Р’В»Р В РЎвЂўР В Р вЂ ."
        )
        try:
            response = await self._client.responses.create(
                model=self._model,
                input=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Р В РЎСџР В РЎвЂўР В Р’В»Р РЋР Р‰Р В Р’В·Р В РЎвЂўР В Р вЂ Р В Р’В°Р РЋРІР‚С™Р В Р’ВµР В Р’В»Р РЋР Р‰Р РЋР С“Р В РЎвЂќР В РЎвЂР В РІвЂћвЂ“ Р В Р’В·Р В Р’В°Р В РЎвЂ”Р РЋР вЂљР В РЎвЂўР РЋР С“: {user_text}\n"
                            f"Р В РЎС›Р В Р’ВµР В РЎвЂќР РЋРЎвЂњР РЋРІР‚В°Р В Р’ВµР В Р’Вµ Р В Р’В»Р В РЎвЂўР В РЎвЂќР В Р’В°Р В Р’В»Р РЋР Р‰Р В Р вЂ¦Р В РЎвЂўР В Р’Вµ Р В Р вЂ Р РЋР вЂљР В Р’ВµР В РЎВР РЋР РЏ ({settings.app_timezone}): {now.isoformat()}\n"
                            f"Р В РЎС›Р В Р’ВµР В РЎвЂќР РЋРЎвЂњР РЋРІР‚В°Р В РЎвЂР В РІвЂћвЂ“ search_text: {current_search_text}"
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
    if normalized.get("command") == "create_reminders":
        reminders = normalized.get("reminders")
        if isinstance(reminders, list):
            fixed: list[dict[str, Any]] = []
            for item in reminders:
                if not isinstance(item, dict):
                    fixed.append(item)
                    continue
                current = dict(item)
                run_at_value = current.get("run_at")
                day_ref = current.get("day_reference")
                if (
                    isinstance(run_at_value, str)
                    and day_ref is not None
                    and re.fullmatch(r"\d{1,2}[:\-]\d{2}", run_at_value.strip())
                ):
                    current["time"] = run_at_value.strip()
                    current["explicit_time_provided"] = True
                    current.pop("run_at", None)
                fixed.append(current)
            normalized["reminders"] = fixed

    if normalized.get("command") == "delete_reminders":
        if "status" not in normalized and "filter_status" in normalized:
            normalized["status"] = normalized.get("filter_status")
        if "reminder_id" not in normalized:
            if "id" in normalized:
                normalized["reminder_id"] = normalized.get("id")
            elif "reminderId" in normalized:
                normalized["reminder_id"] = normalized.get("reminderId")
    return normalized
