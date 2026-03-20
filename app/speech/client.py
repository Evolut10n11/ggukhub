from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any

import httpx

from app.config import Settings


class SpeechToTextError(RuntimeError):
    pass


class SpeechToTextClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._transport = transport
        self._local_model: Any | None = None
        self._local_model_lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._settings.speech_enabled and self._settings.speech_base_url and self._settings.speech_model)

    @property
    def _is_local_mode(self) -> bool:
        return self._settings.speech_base_url.strip().lower().startswith("local://")

    async def transcribe_audio(
        self,
        *,
        audio_bytes: bytes,
        filename: str = "voice.ogg",
        content_type: str = "audio/ogg",
    ) -> str:
        if not self.enabled:
            raise SpeechToTextError("Speech recognition is disabled")
        if not audio_bytes:
            raise SpeechToTextError("Empty audio payload")
        if self._is_local_mode:
            return await self._transcribe_local(audio_bytes=audio_bytes, filename=filename)
        if "api.openai.com" in self._settings.speech_base_url and not self._settings.speech_api_key:
            raise SpeechToTextError("SPEECH_API_KEY is required for OpenAI speech endpoint")

        url = f"{self._settings.speech_base_url.rstrip('/')}/audio/transcriptions"
        headers: dict[str, str] = {}
        if self._settings.speech_api_key:
            headers["Authorization"] = f"Bearer {self._settings.speech_api_key}"

        files: dict[str, tuple[str, bytes, str]] = {
            "file": (filename, audio_bytes, content_type),
        }
        data: dict[str, str] = {
            "model": self._settings.speech_model,
        }
        if self._settings.speech_language:
            data["language"] = self._settings.speech_language

        try:
            async with httpx.AsyncClient(
                timeout=self._settings.speech_timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(url, headers=headers, files=files, data=data)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as error:
            raise SpeechToTextError(f"Speech API error: {error}") from error

        return self._extract_text(payload)

    async def _transcribe_local(self, *, audio_bytes: bytes, filename: str) -> str:
        model = await self._get_local_model()
        suffix = os.path.splitext(filename)[1] or ".ogg"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp.write(audio_bytes)
            temp_path = temp.name

        try:
            text = await asyncio.to_thread(self._transcribe_with_model, model, temp_path)
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

        if text:
            return text
        raise SpeechToTextError("Local Whisper returned empty text")

    async def _get_local_model(self) -> Any:
        if self._local_model is not None:
            return self._local_model

        async with self._local_model_lock:
            if self._local_model is not None:
                return self._local_model

            try:
                from faster_whisper import WhisperModel
            except ImportError as error:
                raise SpeechToTextError(
                    "Local Whisper dependencies are missing. Install: pip install faster-whisper"
                ) from error

            try:
                self._local_model = WhisperModel(
                    self._settings.speech_model,
                    device=self._settings.speech_device,
                    compute_type=self._settings.speech_compute_type,
                )
            except Exception as error:
                raise SpeechToTextError(f"Cannot initialize local Whisper model: {error}") from error

        return self._local_model

    def _transcribe_with_model(self, model: Any, audio_path: str) -> str:
        language = self._settings.speech_language or None
        try:
            segments, _ = model.transcribe(
                audio_path,
                language=language,
                vad_filter=True,
                beam_size=5,
            )
        except Exception as error:
            raise SpeechToTextError(f"Local Whisper inference failed: {error}") from error

        chunks: list[str] = []
        for segment in segments:
            text = str(getattr(segment, "text", "")).strip()
            if text:
                chunks.append(text)
        return " ".join(chunks).strip()

    def close(self) -> None:
        if self._local_model is not None:
            del self._local_model
            self._local_model = None

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        alt = payload.get("result")
        if isinstance(alt, str) and alt.strip():
            return alt.strip()

        raise SpeechToTextError("Speech API returned empty text")
