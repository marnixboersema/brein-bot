"""OpenAI Whisper / gpt-4o-transcribe wrapper."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from openai import AsyncOpenAI

# Telegram upload limit for Whisper-style endpoints
MAX_AUDIO_BYTES = 25 * 1024 * 1024


class AudioTooLarge(ValueError):
    pass


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])


async def transcribe_voice(audio_path: Path | str, *, language: str = "af") -> str:
    """Return plain-text transcript. Raises AudioTooLarge if file > 25 MB."""
    path = Path(audio_path)
    if path.stat().st_size > MAX_AUDIO_BYTES:
        raise AudioTooLarge(f"audio file is {path.stat().st_size} bytes, max {MAX_AUDIO_BYTES}")
    client = _client()
    with path.open("rb") as fh:
        result = await client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            language=language,
            file=fh,
        )
    return (result.text or "").strip()
