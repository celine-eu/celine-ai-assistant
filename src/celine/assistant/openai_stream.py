from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator

from openai import AsyncOpenAI

from .settings import settings
from .skills import SkillRegistry

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

You have access to tools. Use them when the user's question requires live data or document lookups.
Do not guess values that can be fetched via tools.
"""


def _build_system_prompt(skill_registry: SkillRegistry) -> str:
    fragments = skill_registry.get_system_prompt_fragments()
    if not fragments:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + "\n\nAvailable capabilities:\n" + "\n".join(fragments)


def _word_count(messages: list[dict[str, Any]]) -> int:
    total = 0
    for m in messages:
        c = m.get("content", "")
        if isinstance(c, str) and c:
            total += len(c.split())
    return total


async def _summarize_messages(
    client: AsyncOpenAI,
    messages: list[dict[str, Any]],
) -> str:
    text_parts = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            text_parts.append(f"{role}: {content}")

    conversation = "\n\n".join(text_parts)

    summary = await client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Summarize the following conversation concisely. "
                    "Preserve key decisions, topics discussed, and any data referenced. "
                    "Use bullet points."
                ),
            },
            {"role": "user", "content": conversation},
        ],
        temperature=0.2,
    )
    return summary.choices[0].message.content or ""


def build_context_messages(
    history: list[dict[str, Any]],
    context_blocks: list[dict[str, Any]],
    user_message: str,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []

    for m in history:
        role = m.get("role", "")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    if context_blocks:
        context_text = "\n\n".join(
            f"[SOURCE {i + 1}] {b.get('source')}\n{b.get('text')}"
            for i, b in enumerate(context_blocks)
        )
        messages.append({
            "role": "user",
            "content": f"Context:\n{context_text}\n\nQuestion: {user_message}",
        })
    else:
        messages.append({"role": "user", "content": user_message})

    return messages


def _sse(event_type: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


def _truncate_tool_result(result: str, max_chars: int) -> str:
    if len(result) <= max_chars:
        return result
    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict) and "results" in parsed:
            items = parsed["results"]
            while len(json.dumps(parsed)) > max_chars and len(items) > 3:
                items.pop()
            parsed["truncated"] = True
            return json.dumps(parsed, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        pass
    return result[:max_chars] + "\n...(truncated)"


async def stream_chat(
    *,
    user_message: str,
    context_blocks: list[dict[str, Any]],
    history: list[dict[str, Any]] | None = None,
    skill_registry: SkillRegistry | None = None,
) -> AsyncGenerator[str, None]:
    client = _client()

    system_prompt = (
        _build_system_prompt(skill_registry)
        if skill_registry
        else SYSTEM_PROMPT
    )

    context_messages = build_context_messages(
        history or [],
        context_blocks,
        user_message,
    )

    wc = _word_count(context_messages)
    if wc > settings.chat_word_limit and len(context_messages) > settings.chat_hot_messages:
        older = context_messages[: -settings.chat_hot_messages]
        hot = context_messages[-settings.chat_hot_messages :]
        summary = await _summarize_messages(client, older)
        context_messages = [
            {"role": "user", "content": f"[Summary of earlier conversation]\n\n{summary}"},
            {"role": "assistant", "content": "Understood. I have the context from our earlier discussion."},
            *hot,
        ]

    api_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *context_messages,
    ]

    tools = skill_registry.get_tools() if skill_registry else []

    async for chunk in _agentic_loop(client, api_messages, tools, skill_registry):
        yield chunk


async def _agentic_loop(
    client: AsyncOpenAI,
    api_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    skill_registry: SkillRegistry | None,
) -> AsyncGenerator[str, None]:
    max_rounds = settings.max_tool_rounds
    max_result_chars = settings.max_tool_result_chars

    for _round in range(max_rounds):
        log.info(
            "agentic_round_%d: %d messages",
            _round, len(api_messages),
        )
        t0 = time.monotonic()

        create_kwargs: dict[str, Any] = {
            "model": settings.openai_chat_model,
            "messages": api_messages,
            "temperature": 0.2,
            "stream": True,
        }
        if tools:
            create_kwargs["tools"] = tools
            create_kwargs["parallel_tool_calls"] = False

        try:
            stream = await client.chat.completions.create(**create_kwargs)
        except Exception as exc:
            log.error("llm_call_failed_round_%d: %s", _round, exc)
            yield _sse("error", {"message": f"LLM request failed: {exc}"})
            break

        text_chunks: list[str] = []
        tool_calls_acc: dict[int, dict[str, str]] = {}
        finish_reason = None

        try:
            async for event in stream:
                if not event.choices:
                    continue
                delta = event.choices[0].delta
                finish_reason = event.choices[0].finish_reason

                if delta and delta.content:
                    text_chunks.append(delta.content)
                    yield _sse("token", delta.content)

                if delta and delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc.id or "",
                                "name": "",
                                "arguments": "",
                            }
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_acc[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls_acc[idx]["arguments"] += tc.function.arguments
        except Exception as exc:
            log.error("llm_stream_failed_round_%d: %s", _round, exc)
            yield _sse("error", {"message": f"Stream interrupted: {exc}"})
            break

        elapsed = time.monotonic() - t0
        log.info(
            "agentic_round_%d_done: %.2fs finish=%s text=%d tools=%d",
            _round, elapsed, finish_reason, len("".join(text_chunks)), len(tool_calls_acc),
        )

        if finish_reason != "tool_calls" or not tool_calls_acc or not skill_registry:
            break

        assistant_msg: dict[str, Any] = {"role": "assistant"}
        if text_chunks:
            assistant_msg["content"] = "".join(text_chunks)
        assistant_msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                },
            }
            for tc in tool_calls_acc.values()
        ]
        api_messages.append(assistant_msg)

        for tc in tool_calls_acc.values():
            try:
                args = json.loads(tc["arguments"])
            except json.JSONDecodeError:
                args = {}

            log.info("tool_start: %s args=%s", tc["name"], args)
            yield _sse("tool_start", {"tool": tc["name"], "args": args})

            progress_queue: asyncio.Queue[str] = asyncio.Queue()

            async def _on_progress(msg: str) -> None:
                await progress_queue.put(msg)

            tool_task = asyncio.create_task(
                skill_registry.execute(
                    tc["name"], args, on_progress=_on_progress
                )
            )

            while not tool_task.done():
                try:
                    msg = await asyncio.wait_for(progress_queue.get(), timeout=0.2)
                    yield _sse("tool_progress", {"tool": tc["name"], "message": msg})
                except asyncio.TimeoutError:
                    continue

            while not progress_queue.empty():
                msg = progress_queue.get_nowait()
                yield _sse("tool_progress", {"tool": tc["name"], "message": msg})

            try:
                result = tool_task.result()
                log.info("tool_done: %s (%d chars)", tc["name"], len(result))
            except Exception as exc:
                log.error("tool_failed: %s %s", tc["name"], exc, exc_info=True)
                result = json.dumps({"error": str(exc)})
                yield _sse("tool_error", {"tool": tc["name"], "error": str(exc)})

            yield _sse("tool_result", {"tool": tc["name"]})

            result = _truncate_tool_result(result, max_result_chars)
            api_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })
