from __future__ import annotations

import io
import logging
from typing import Any, Literal

import httpx
from openai import AsyncOpenAI

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class SpeechToTextService:
    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        http_client: httpx.AsyncClient | None = None,
        provider: Literal["openai", "http", "groq"] | None = None,
        groq_api_key: str | None = None,
    ) -> None:
        settings = get_settings()
        self._provider = provider or settings.stt_provider
        self._model = settings.groq_stt_model if self._provider == "groq" else settings.openai_transcription_model
        self._http_url = settings.stt_http_url
        self._http_timeout = settings.stt_http_timeout_seconds
        self._groq_url = settings.groq_stt_base_url.rstrip("/") + "/audio/transcriptions"
        self._groq_api_key = groq_api_key or settings.groq_api_key
        self._groq_language = settings.groq_stt_language
        self._groq_timeout = settings.groq_stt_timeout_seconds
        self._http_client = http_client
        self._client = client
        if self._provider == "openai" and self._client is None:
            self._client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                max_retries=0,
                http_client=httpx.AsyncClient(trust_env=False, timeout=60.0),
            )

    async def transcribe_bytes(
        self,
        *,
        payload: bytes,
        filename: str = "voice.ogg",
    ) -> str | None:
        if not payload:
            return None

        if self._provider == "http":
            return await self._transcribe_via_http(payload=payload, filename=filename)
        if self._provider == "groq":
            return await self._transcribe_via_groq(payload=payload, filename=filename)

        stream = io.BytesIO(payload)
        stream.name = filename
        try:
            assert self._client is not None
            result = await self._client.audio.transcriptions.create(
                model=self._model,
                file=stream,
            )
        except Exception:
            logger.exception("Failed to transcribe audio payload")
            return None

        text = getattr(result, "text", None)
        if text is None and isinstance(result, str):
            text = result
        if not isinstance(text, str):
            return None
        text = text.strip()
        return text or None

    async def _transcribe_via_groq(self, *, payload: bytes, filename: str) -> str | None:
        if not self._groq_api_key:
            logger.error("GROQ_API_KEY is required for Groq STT provider")
            return None

        headers = {"Authorization": f"Bearer {self._groq_api_key}"}
        data = {
            "model": self._model,
            "language": self._groq_language,
            "response_format": "json",
            "temperature": "0",
        }
        files = {"file": (filename, payload)}
        try:
            if self._http_client is not None:
                response = await self._http_client.post(self._groq_url, data=data, files=files, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=self._groq_timeout, trust_env=False) as client:
                    response = await client.post(self._groq_url, data=data, files=files, headers=headers)
            response.raise_for_status()
            payload_json: Any = response.json()
        except Exception:
            logger.exception("Failed to transcribe audio payload via Groq STT")
            return None

        text = payload_json.get("text") if isinstance(payload_json, dict) else None
        if not isinstance(text, str):
            return None
        text = text.strip()
        return text or None

    async def _transcribe_via_http(self, *, payload: bytes, filename: str) -> str | None:
        headers = {
            "Content-Type": "application/octet-stream",
            "X-Filename": filename,
        }
        try:
            if self._http_client is not None:
                response = await self._http_client.post(self._http_url, content=payload, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=self._http_timeout, trust_env=False) as client:
                    response = await client.post(self._http_url, content=payload, headers=headers)
            response.raise_for_status()
            data: Any = response.json()
        except Exception:
            logger.exception("Failed to transcribe audio payload via HTTP STT")
            return None

        text = data.get("text") if isinstance(data, dict) else None
        if not isinstance(text, str):
            return None
        text = text.strip()
        return text or None
