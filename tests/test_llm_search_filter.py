from datetime import datetime, timezone

import pytest

from app.services.llm_service import LLMService


class DummyClient:
    class Responses:
        def __init__(self, output_text: str) -> None:
            self._output_text = output_text

        async def create(self, **kwargs):
            class Usage:
                input_tokens = 10
                output_tokens = 10

            class Response:
                usage = Usage()

                def __init__(self, output_text: str) -> None:
                    self.output_text = output_text

            return Response(self._output_text)

    def __init__(self, output_text: str) -> None:
        self.responses = DummyClient.Responses(output_text)


@pytest.mark.asyncio
async def test_list_filter_phrase_enriches_missing_search_text() -> None:
    client = DummyClient('{"command":"list_reminders","mode":"all"}')
    service = LLMService(client=client)
    command = await service.build_command(
        "Показать все напоминания где упоминается молоко",
        now=datetime(2026, 2, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert command.command == "list_reminders"
    assert command.search_text == "молоко"


@pytest.mark.asyncio
async def test_existing_search_text_from_llm_is_kept() -> None:
    client = DummyClient('{"command":"list_reminders","mode":"search","search_text":"клиент"}')
    service = LLMService(client=client)
    command = await service.build_command(
        "Покажи где упоминается молоко",
        now=datetime(2026, 2, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert command.command == "list_reminders"
    assert command.search_text == "клиент"


@pytest.mark.asyncio
async def test_list_date_phrase_enriches_missing_range() -> None:
    client = DummyClient('{"command":"list_reminders","mode":"all"}')
    service = LLMService(client=client)
    command = await service.build_command(
        "Показать все напоминания на 24 февраля",
        now=datetime(2026, 2, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert command.command == "list_reminders"
    assert command.mode == "range"
    assert command.from_dt == datetime(2026, 2, 24, 0, 0, tzinfo=timezone.utc)
    assert command.to_dt == datetime(2026, 2, 24, 23, 59, 59, 999999, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_list_date_and_search_phrase_combines_filters() -> None:
    client = DummyClient('{"command":"list_reminders","mode":"all"}')
    service = LLMService(client=client)
    command = await service.build_command(
        "Показать все напоминания на 24 февраля где упоминается молоко",
        now=datetime(2026, 2, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert command.command == "list_reminders"
    assert command.mode == "range"
    assert command.search_text == "молоко"


@pytest.mark.asyncio
async def test_list_date_interval_phrase_enriches_range() -> None:
    client = DummyClient('{"command":"list_reminders","mode":"all"}')
    service = LLMService(client=client)
    command = await service.build_command(
        "Показать все напоминания в диапазоне 24-26 февраля",
        now=datetime(2026, 2, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert command.command == "list_reminders"
    assert command.mode == "range"
    assert command.from_dt == datetime(2026, 2, 24, 0, 0, tzinfo=timezone.utc)
    assert command.to_dt == datetime(2026, 2, 26, 23, 59, 59, 999999, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_list_this_week_phrase_enriches_range() -> None:
    client = DummyClient('{"command":"list_reminders","mode":"all"}')
    service = LLMService(client=client)
    command = await service.build_command(
        "Покажи напоминания на этой неделе",
        now=datetime(2026, 2, 22, 12, 0, tzinfo=timezone.utc),  # Sunday
    )
    assert command.command == "list_reminders"
    assert command.mode == "range"
    assert command.from_dt == datetime(2026, 2, 16, 0, 0, tzinfo=timezone.utc)
    assert command.to_dt == datetime(2026, 2, 22, 23, 59, 59, 999999, tzinfo=timezone.utc)
