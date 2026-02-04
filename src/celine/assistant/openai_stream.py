from __future__ import annotations

import logging
from typing import AsyncGenerator, Any

from openai import AsyncOpenAI

from .settings import settings

log = logging.getLogger(__name__)


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key)


SYSTEM_PROMPT = """You are an expert of renewable energy communities and energy digitalization topics and helpful assistant answering questions using the provided context.
If the context does not contain the answer and you are unsure about the answer, say you don't know and suggest what information is missing.
Be concise and accurate. Do not fabricate citations or sources.
Your target user is a participant in the energy communities part of the CELINE EU project.
Adapt to user style, use same language if possible.
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
