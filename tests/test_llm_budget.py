import pytest
import httpx
from datetime import datetime, timezone
from openai import APITimeoutError

from app.core.settings import get_settings
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


class TimeoutChatClient:
    class Chat:
        class Completions:
            def __init__(self) -> None:
                self.calls = 0

            async def create(self, **kwargs):
                self.calls += 1
                request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
                raise APITimeoutError(request=request)

        def __init__(self) -> None:
            self.completions = TimeoutChatClient.Chat.Completions()

    def __init__(self) -> None:
        self.chat = TimeoutChatClient.Chat()


@pytest.mark.asyncio
async def test_llm_service_blocks_when_budget_exceeded() -> None:
    guard = MonthlyCostGuard(monthly_usd_limit=0.0)
    service = LLMService(client=DummyClient(), cost_guard=guard, provider="openai")
    now = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(LLMBudgetExceededError):
        await service.build_command("покажи все", now=now)


@pytest.mark.asyncio
async def test_llm_service_uses_configured_attempt_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "1")
    get_settings.cache_clear()
    client = TimeoutChatClient()
    service = LLMService(client=client, provider="deepseek")
    now = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)

    try:
        with pytest.raises(APITimeoutError):
            await service.build_command("напомни проверить сервер", now=now)
    finally:
        get_settings.cache_clear()

    assert client.chat.completions.calls == 1
