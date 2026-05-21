"""OpenAI gpt-4o vision OCR."""
from __future__ import annotations

import base64
import os
from pathlib import Path

from openai import AsyncOpenAI

OCR_PROMPT = (
    "Onttrek alle teks uit hierdie beeld presies soos dit verskyn. "
    "Behou struktuur. Geen kommentaar of opsommings nie."
)


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])


def _mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/jpeg")


async def ocr_image(image_path: Path | str) -> str:
    path = Path(image_path)
    mime = _mime_for(path)
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    client = _client()
    result = await client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
    )
    return (result.choices[0].message.content or "").strip()
