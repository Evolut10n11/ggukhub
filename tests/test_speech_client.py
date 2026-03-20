import httpx
import pytest

from app.config.settings import Settings
from app.speech.client import SpeechToTextClient, SpeechToTextError


def _settings(*, speech_enabled: bool = True) -> Settings:
    return Settings(
        telegram_bot_token="test-token",

        speech_enabled=speech_enabled,
        speech_base_url="http://stt.local/v1",
        speech_model="whisper-1",
        speech_language="ru",
    )


@pytest.mark.asyncio
async def test_transcribe_audio_success() -> None:
    async def _handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://stt.local/v1/audio/transcriptions"
        return httpx.Response(status_code=200, json={"text": "Leak in entrance"})

    transport = httpx.MockTransport(_handler)
    client = SpeechToTextClient(_settings(), transport=transport)

    text = await client.transcribe_audio(audio_bytes=b"voice-bytes")
    assert text == "Leak in entrance"


@pytest.mark.asyncio
async def test_transcribe_audio_empty_payload_raises() -> None:
    async def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json={"text": ""})

    transport = httpx.MockTransport(_handler)
    client = SpeechToTextClient(_settings(), transport=transport)

    with pytest.raises(SpeechToTextError):
        await client.transcribe_audio(audio_bytes=b"voice-bytes")


@pytest.mark.asyncio
async def test_transcribe_audio_disabled_raises() -> None:
    client = SpeechToTextClient(_settings(speech_enabled=False))

    with pytest.raises(SpeechToTextError):
        await client.transcribe_audio(audio_bytes=b"voice-bytes")


@pytest.mark.asyncio
async def test_transcribe_audio_openai_without_api_key_raises() -> None:
    settings = Settings(
        telegram_bot_token="test-token",

        speech_enabled=True,
        speech_base_url="https://api.openai.com/v1",
        speech_model="gpt-4o-transcribe",
        speech_api_key="",
    )
    client = SpeechToTextClient(settings)

    with pytest.raises(SpeechToTextError):
        await client.transcribe_audio(audio_bytes=b"voice-bytes")


@pytest.mark.asyncio
async def test_transcribe_audio_local_mode() -> None:
    settings = Settings(
        telegram_bot_token="test-token",

        speech_enabled=True,
        speech_base_url="local://faster-whisper",
        speech_model="small",
    )
    client = SpeechToTextClient(settings)

    async def _fake_local(*, audio_bytes: bytes, filename: str) -> str:
        assert audio_bytes == b"voice-bytes"
        assert filename == "voice.ogg"
        return "Local whisper text"

    client._transcribe_local = _fake_local  # type: ignore[method-assign]

    text = await client.transcribe_audio(audio_bytes=b"voice-bytes")
    assert text == "Local whisper text"
