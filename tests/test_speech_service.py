import httpx
import pytest

from app.services.speech_service import SpeechToTextService


@pytest.mark.asyncio
async def test_http_stt_provider_returns_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/transcribe"
        assert request.headers["content-type"] == "application/octet-stream"
        assert request.headers["x-filename"] == "voice.ogg"
        assert await request.aread() == b"audio-bytes"
        return httpx.Response(200, json={"text": " напомни завтра "})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = SpeechToTextService(http_client=client, provider="http")
        result = await service.transcribe_bytes(payload=b"audio-bytes", filename="voice.ogg")

    assert result == "напомни завтра"


@pytest.mark.asyncio
async def test_http_stt_provider_returns_none_for_empty_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "   "})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = SpeechToTextService(http_client=client, provider="http")
        result = await service.transcribe_bytes(payload=b"audio-bytes")

    assert result is None
