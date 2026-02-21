import pytest
from datetime import datetime, timezone

from app.services.cost_control import MonthlyCostGuard
from app.services.llm_service import LLMBudgetExceededError, LLMService


class DummyClient:
    class Responses:
        async def create(self, **kwargs):
            class Usage:
                input_tokens = 10
                output_tokens = 10

            class Response:
                output_text = '{"command":"list_reminders","mode":"all"}'
                usage = Usage()

            return Response()

    def __init__(self) -> None:
        self.responses = DummyClient.Responses()


@pytest.mark.asyncio
async def test_llm_service_blocks_when_budget_exceeded() -> None:
    guard = MonthlyCostGuard(monthly_usd_limit=0.0)
    service = LLMService(client=DummyClient(), cost_guard=guard)
    now = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(LLMBudgetExceededError):
        await service.build_command("покажи все", now=now)

