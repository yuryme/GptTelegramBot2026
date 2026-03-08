from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.services.llm_service import parse_assistant_command
from app.telegram import handlers


@dataclass
class _FakeCreated:
    id: int
    text: str
    run_at: datetime
    recurrence_rule: str | None = None


class _FakeRepo:
    async def log_action(self, **kwargs):
        return None


class _FakeService:
    def __init__(self, repository):
        self._repository = _FakeRepo()

    async def create_from_command(self, chat_id, command):
        return [_FakeCreated(id=1, text="тест", run_at=datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc))]

    async def list_from_command(self, chat_id, command):
        return []

    async def delete_from_command(self, chat_id, command):
        raise AssertionError("delete не должен вызываться в этом тесте")


class _FakeSessionCtx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _FakeLimiter:
    def allow(self, chat_id: int) -> bool:
        return True


class _FakeMessage:
    def __init__(self, chat_id: int):
        self.chat = type("Chat", (), {"id": chat_id})()
        self.replies: list[str] = []

    async def answer(self, text: str, reply_markup=None):
        self.replies.append(text)


@pytest.mark.asyncio
async def test_text_voice_parity_for_same_business_text(monkeypatch) -> None:
    command = parse_assistant_command(
        {
            "command": "create_reminders",
            "reminders": [
                {
                    "text": "тест",
                    "run_at": "2026-03-10T10:00:00+00:00",
                    "explicit_time_provided": True,
                }
            ],
        }
    )

    class _LLMStub:
        async def build_command(self, text: str):
            return command

    monkeypatch.setattr(handlers, "llm_service", _LLMStub())
    monkeypatch.setattr(handlers, "chat_rate_limiter", _FakeLimiter())
    monkeypatch.setattr(handlers, "SessionLocal", _FakeSessionCtx)
    monkeypatch.setattr(handlers, "ReminderService", _FakeService)

    text_message = _FakeMessage(chat_id=1)
    voice_message = _FakeMessage(chat_id=1)

    await handlers._handle_business_text(message=text_message, text="напомни тест", source_text="напомни тест")
    await handlers._handle_business_text(
        message=voice_message,
        text="напомни тест",
        source_text="[voice] напомни тест",
    )

    assert len(text_message.replies) == 1
    assert len(voice_message.replies) == 1
    assert text_message.replies[0] == voice_message.replies[0]
    assert text_message.replies[0].startswith("Созданные напоминания:")
