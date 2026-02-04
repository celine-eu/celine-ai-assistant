from __future__ import annotations

import base64
from openai import AsyncOpenAI

from .settings import settings


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def describe_image(*, image_bytes: bytes, filename: str | None = None) -> str:
    client = _client()
    b64 = base64.b64encode(image_bytes).decode("ascii")
    mime = "image/png"
    if filename:
        lower = filename.lower()
        if lower.endswith(".jpg") or lower.endswith(".jpeg"):
            mime = "image/jpeg"
        elif lower.endswith(".webp"):
            mime = "image/webp"

    prompt = (
        "Describe this image for retrieval in a knowledge base. "
        "Include: what it shows, any visible text (transcribe), entities, and key details. "
        "Write as compact factual bullet points."
    )

    resp = await client.chat.completions.create(
        model=settings.openai_vision_model,
        messages=[
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]},
        ],
        temperature=0.2,
    )
    return (resp.choices[0].message.content or "").strip()
