from __future__ import annotations

import io
import logging

from openai import AsyncOpenAI

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class SpeechToTextService:
    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        settings = get_settings()
        self._model = settings.openai_transcription_model
        self._client = client or AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0)

    async def transcribe_bytes(
        self,
        *,
        payload: bytes,
        filename: str = "voice.ogg",
    ) -> str | None:
        if not payload:
            return None

        stream = io.BytesIO(payload)
        stream.name = filename
        try:
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
