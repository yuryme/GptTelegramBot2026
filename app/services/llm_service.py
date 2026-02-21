from __future__ import annotations

import json
import logging
from asyncio import sleep
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI
from openai import APIConnectionError, APITimeoutError, RateLimitError
from pydantic import ValidationError

from app.core.settings import get_settings
from app.llm.prompts import SYSTEM_PROMPT_RU
from app.schemas.commands import AssistantCommand, assistant_command_adapter
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
        now = now or datetime.now(timezone.utc)
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
                                f"Текущее время UTC: {now.isoformat()}\n"
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
        return parse_assistant_command(raw_output)


def parse_assistant_command(raw_output: str | dict[str, Any]) -> AssistantCommand:
    payload: dict[str, Any]
    if isinstance(raw_output, str):
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise LLMCommandValidationError("LLM output is not valid JSON") from exc
    else:
        payload = raw_output

    try:
        return assistant_command_adapter.validate_python(payload)
    except ValidationError as exc:
        raise LLMCommandValidationError("LLM command does not match schema") from exc
