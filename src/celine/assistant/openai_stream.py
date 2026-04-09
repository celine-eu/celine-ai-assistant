from __future__ import annotations

import logging
from typing import AsyncGenerator, Any

from openai import AsyncOpenAI

from .settings import settings

log = logging.getLogger(__name__)


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key)


SYSTEM_PROMPT = """You are a helpful assistant for participants in the energy communities and energy digitalization topics part of the CELINE EU project.
Answer using the provided context when possible.
If the context does not contain the answer and you are unsure, say clearly that you do not know and explain briefly what information is missing.

Your target user is a non-technical end user.
Use simple language, short sentences, and practical explanations.
Avoid jargon, long introductions, and unnecessary detail.
Keep the answer brief by default: usually 2 to 4 short sentences.
Use bullet points only when they make the answer easier to understand.
If the user asks for more detail, then expand the explanation.
Adapt to the user's language and tone when possible.
Be accurate. Do not fabricate citations or sources.
"""


async def stream_chat(
    *,
    user_message: str,
    context_blocks: list[dict[str, Any]],
) -> AsyncGenerator[str, None]:
    client = _client()
    context_text = "\n\n".join(
        f"[SOURCE {i+1}] {b.get('source')}\n{b.get('text')}"
        for i, b in enumerate(context_blocks)
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Context:\n{context_text}\n\nQuestion: {user_message}",
        },
    ]

    stream = await client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=messages,
        temperature=0.2,
        stream=True,
    )

    async for event in stream:
        try:
            delta = event.choices[0].delta
            if delta and delta.content:
                yield delta.content
        except Exception:
            continue
