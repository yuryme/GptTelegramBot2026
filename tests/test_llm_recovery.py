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

            output = self._output_texts.pop(0)
            return Response(output)

    def __init__(self, output_texts: list[str]) -> None:
        self.responses = DummyClient.Responses(output_texts)


@pytest.mark.asyncio
async def test_recovers_invalid_first_llm_output() -> None:
    client = DummyClient(
        [
            "Это не JSON",
            '{"command":"list_reminders","mode":"range","from_dt":"2026-02-01T00:00:00+00:00","to_dt":"2026-02-28T23:59:59.999999+00:00"}',
        ]
    )
    service = LLMService(client=client)
    command = await service.build_command(
        "Показать все напоминания в этом месяце",
        now=datetime(2026, 2, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert command.command == "list_reminders"
    assert command.mode == "range"
