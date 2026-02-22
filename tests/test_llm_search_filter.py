from datetime import datetime, timezone

import pytest

from app.services.llm_service import LLMService


class DummyClient:
    class Responses:
        def __init__(self, output_texts: list[str]) -> None:
            self._output_texts = output_texts

        async def create(self, **kwargs):
            class Usage:
                input_tokens = 10
                output_tokens = 10

            class Response:
                usage = Usage()

                def __init__(self, output_text: str) -> None:
                    self.output_text = output_text

            if not self._output_texts:
                raise RuntimeError("No more mocked responses")
            return Response(self._output_texts.pop(0))

    def __init__(self, output_texts: list[str]) -> None:
        self.responses = DummyClient.Responses(output_texts)


@pytest.mark.asyncio
async def test_list_query_refined_with_search_filter() -> None:
    client = DummyClient(
        [
            '{"command":"list_reminders","mode":"all"}',
            '{"command":"list_reminders","mode":"search","search_text":"молоко"}',
            '{"search_text":"молок"}',
        ]
    )
    service = LLMService(client=client)
    command = await service.build_command(
        "Показать все напоминания где упоминается молоко",
        now=datetime(2026, 2, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert command.command == "list_reminders"
    assert command.mode == "search"
    assert command.search_text == "молок"


@pytest.mark.asyncio
async def test_list_query_refined_with_date_range() -> None:
    client = DummyClient(
        [
            '{"command":"list_reminders","mode":"all"}',
            '{"command":"list_reminders","mode":"range","from_dt":"2026-02-24T00:00:00+00:00","to_dt":"2026-02-26T23:59:59.999999+00:00"}',
        ]
    )
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
async def test_list_query_with_existing_filter_is_not_refined() -> None:
    client = DummyClient(
        [
            '{"command":"list_reminders","mode":"search","search_text":"клиент"}',
            '{"search_text":"клиент"}',
        ]
    )
    service = LLMService(client=client)
    command = await service.build_command(
        "Покажи где упоминается клиент",
        now=datetime(2026, 2, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert command.command == "list_reminders"
    assert command.mode == "search"
    assert command.search_text == "клиент"
