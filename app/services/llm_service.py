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
from app.schemas.commands import AssistantCommand, assistant_command_adapter
from app.services.cost_control import MonthlyCostGuard
from app.services.guardrails import LLMCircuitBreaker
from app.services.temporal_normalizer import TemporalNormalizer


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
        self._client = client or AsyncOpenAI(
            api_key=settings.openai_api_key,
            max_retries=0,
            http_client=httpx.AsyncClient(trust_env=False, timeout=30.0),
        )
        self._cost_guard = cost_guard or MonthlyCostGuard(
            monthly_usd_limit=settings.openai_monthly_budget_usd,
            estimated_input_cost_per_1k=settings.openai_estimated_input_cost_per_1k,
            estimated_output_cost_per_1k=settings.openai_estimated_output_cost_per_1k,
        )
        self._circuit_breaker = circuit_breaker or LLMCircuitBreaker(
            failure_threshold=settings.llm_circuit_failure_threshold,
            open_seconds=settings.llm_circuit_open_seconds,
        )
        self._temporal_normalizer = TemporalNormalizer(timezone=settings.app_timezone)
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
            async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
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

        command = self._temporal_normalizer.normalize_command(command=command, user_text=user_text, now=now)

        # Fast path: skip extra refinement/normalization LLM round-trips.
        # This keeps latency predictable by relying on the primary parsed command.

        return command

    async def _request_primary_command(self, *, user_text: str, now: datetime) -> str:
        settings = get_settings()
        user_prompt = (
            f"User request: {user_text}\n"
            f"Current local datetime ({settings.app_timezone}): {now.isoformat()}\n"
            "Return exactly one valid JSON object matching the schema. "
            "No markdown, no comments, no extra text."
        )
        response = None
        for attempt in range(2):
            try:
                response = await self._client.responses.create(
                    model=self._model,
                    input=[
                        {"role": "system", "content": SYSTEM_PROMPT_RU},
                        {"role": "user", "content": user_prompt},
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


    async def _recover_command_json_with_llm(
        self,
        *,
        user_text: str,
        raw_output: str,
        now: datetime,
    ) -> AssistantCommand | None:
        settings = get_settings()
        prompt = (
            "Fix invalid assistant output into a strict AssistantCommand JSON. "
            "Allowed command values: create_reminders, list_reminders, delete_reminders. "
            "Return only JSON, no markdown and no explanations."
        )
        user_prompt = (
            f"User request: {user_text}\n"
            f"Current local datetime ({settings.app_timezone}): {now.isoformat()}\n"
            f"Invalid model output to fix: {raw_output}"
        )
        try:
            response = await self._client.responses.create(
                model=self._model,
                input=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_prompt},
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

                if isinstance(day_ref, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_ref.strip()):
                    current["day_reference"] = "specific_date"
                    if "date_value" not in current and "specific_date" not in current:
                        current["date_value"] = day_ref.strip()

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
