"""The agentic loop, against a faked OpenAI client.

The fake is at `client.chat.completions.create` — the narrowest boundary that still
runs our streaming accumulation, our tool dispatch and our SSE framing. Everything
below it (HTTP, retries, the model itself) belongs to `openai` and is not ours to test.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from celine.assistant import openai_stream
from celine.assistant.openai_stream import (
    _agentic_loop,
    _truncate_tool_result,
    _word_count,
    build_context_messages,
    stream_chat,
)
from celine.assistant.settings import settings
from celine.assistant.skills import Skill, SkillRegistry

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def text_chunk(content: str, finish_reason: str | None = None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=None),
                finish_reason=finish_reason,
            )
        ]
    )


def tool_chunk(
    index: int = 0,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
    finish_reason: str | None = None,
):
    fn = SimpleNamespace(name=name, arguments=arguments)
    tc = SimpleNamespace(index=index, id=call_id, function=fn)
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None, tool_calls=[tc]),
                finish_reason=finish_reason,
            )
        ]
    )


def empty_chunk():
    """A chunk with no choices — real streams emit these (usage-only frames)."""
    return SimpleNamespace(choices=[])


class FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    async def __aiter__(self):
        for c in self._chunks:
            if isinstance(c, Exception):
                raise c
            yield c


class FakeCompletions:
    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._rounds:
            raise AssertionError("the loop asked for more rounds than were scripted")
        nxt = self._rounds.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        if not kwargs.get("stream"):
            # the summarisation call, which is not streamed
            return nxt
        return FakeStream(nxt)


class FakeClient:
    def __init__(self, rounds):
        self.completions = FakeCompletions(rounds)
        self.chat = SimpleNamespace(completions=self.completions)


class ScriptedSkill(Skill):
    name = "scripted"

    def __init__(self, result: str = '{"ok": true}', raises: Exception | None = None):
        self._result = result
        self._raises = raises
        self.calls: list[tuple[str, dict]] = []

    def get_tools(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "do_thing",
                    "description": "does a thing",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    async def execute(self, tool_name, arguments, *, on_progress=None):
        self.calls.append((tool_name, arguments))
        if on_progress:
            await on_progress("halfway")
        await asyncio.sleep(0)
        if self._raises:
            raise self._raises
        return self._result


def registry_with(skill: Skill) -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(skill)
    return registry


async def collect(agen) -> list[tuple[str, Any]]:
    """Parse the SSE frames back into (event, data) pairs."""
    events = []
    async for frame in agen:
        head, _, body = frame.partition("\n")
        events.append((head.removeprefix("event: "), json.loads(body.removeprefix("data: ").strip())))
    return events


def types_of(events) -> list[str]:
    return [e for e, _ in events]


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


# @verifies REQ-0023
def test_context_blocks_are_folded_into_the_final_user_turn():
    messages = build_context_messages(
        history=[],
        context_blocks=[
            {"source": "doc-a", "text": "alpha"},
            {"source": "doc-b", "text": "beta"},
        ],
        user_message="what is alpha?",
    )

    (only,) = messages
    assert only["role"] == "user"
    assert "[SOURCE 1] doc-a\nalpha" in only["content"]
    assert "[SOURCE 2] doc-b\nbeta" in only["content"]
    assert only["content"].endswith("Question: what is alpha?")


# @verifies REQ-0023
def test_without_context_the_user_message_is_sent_as_is():
    messages = build_context_messages([], [], "hello")
    assert messages == [{"role": "user", "content": "hello"}]


# @verifies REQ-0012
def test_history_is_replayed_and_anything_that_is_not_a_user_or_assistant_turn_is_dropped():
    messages = build_context_messages(
        history=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "tool", "content": "not replayed"},
            {"role": "assistant", "content": ""},
        ],
        context_blocks=[],
        user_message="third",
    )
    assert messages == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ]


def test_word_count_ignores_non_string_content():
    """Tool-call turns carry a list, not a string. @verifies REQ-0012"""
    assert _word_count([{"role": "user", "content": "one two three"}]) == 3
    assert _word_count([{"role": "assistant", "content": [{"type": "text"}]}]) == 0
    assert _word_count([{"role": "assistant"}]) == 0


# ---------------------------------------------------------------------------
# Tool result truncation
# ---------------------------------------------------------------------------


# @verifies REQ-0030
def test_a_short_result_is_untouched():
    assert _truncate_tool_result("small", 100) == "small"


# @verifies REQ-0030
def test_an_oversized_opaque_result_is_cut_and_marked():
    out = _truncate_tool_result("x" * 200, 50)
    assert out.startswith("x" * 50)
    assert out.endswith("...(truncated)")


def test_an_oversized_result_list_is_shortened_from_the_end():
    """A JSON payload with a `results` list loses whole entries rather than being cut
    mid-token, so what reaches the model is still parseable.

    @verifies REQ-0030
    """
    payload = json.dumps({"results": [{"text": "y" * 40} for _ in range(10)]})
    out = json.loads(_truncate_tool_result(payload, 300))

    assert out["truncated"] is True
    assert 3 <= len(out["results"]) < 10


def test_a_result_list_is_never_shortened_below_three_entries():
    """The floor wins over the budget: the output can still exceed `max_chars`.

    @verifies REQ-0030
    """
    payload = json.dumps({"results": [{"text": "y" * 100} for _ in range(10)]})
    out = json.loads(_truncate_tool_result(payload, 50))

    assert len(out["results"]) == 3
    assert len(json.dumps(out)) > 50


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


# @verifies REQ-0007
async def test_a_plain_answer_streams_tokens_and_stops():
    client = FakeClient([[text_chunk("Hel"), text_chunk("lo"), text_chunk("", "stop")]])

    events = await collect(_agentic_loop(client, [], [], None))

    assert events == [("token", "Hel"), ("token", "lo")]
    assert len(client.completions.calls) == 1


# @verifies REQ-0007
async def test_chunks_with_no_choices_are_skipped():
    client = FakeClient([[empty_chunk(), text_chunk("hi", "stop")]])
    assert await collect(_agentic_loop(client, [], [], None)) == [("token", "hi")]


# @verifies REQ-0025
async def test_a_tool_call_runs_the_skill_and_feeds_the_result_back():
    skill = ScriptedSkill('{"temperature": 21}')
    messages: list[dict] = []
    client = FakeClient(
        [
            [
                tool_chunk(call_id="call-1", name="do_thing", arguments='{"a"'),
                tool_chunk(arguments=': 1}', finish_reason="tool_calls"),
            ],
            [text_chunk("It is 21 degrees.", "stop")],
        ]
    )

    events = await collect(
        _agentic_loop(client, messages, [{"type": "function"}], registry_with(skill))
    )

    assert types_of(events) == [
        "tool_start",
        "tool_progress",
        "tool_result",
        "token",
    ]
    # Arguments are accumulated across deltas before being parsed.
    assert skill.calls == [("do_thing", {"a": 1})]

    assistant_turn, tool_turn = messages
    assert assistant_turn["tool_calls"][0]["function"]["name"] == "do_thing"
    assert tool_turn == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"temperature": 21}',
    }


async def test_a_failing_tool_is_reported_and_the_conversation_continues():
    """The model is told the tool failed and gets another round to explain itself.

    @verifies REQ-0028
    """
    skill = ScriptedSkill(raises=RuntimeError("upstream is down"))
    messages: list[dict] = []
    client = FakeClient(
        [
            [tool_chunk(call_id="c1", name="do_thing", arguments="{}", finish_reason="tool_calls")],
            [text_chunk("I could not reach it.", "stop")],
        ]
    )

    events = await collect(
        _agentic_loop(client, messages, [{"type": "function"}], registry_with(skill))
    )

    assert "tool_error" in types_of(events)
    assert json.loads(messages[-1]["content"]) == {"error": "upstream is down"}


# @verifies REQ-0007
async def test_a_failing_llm_call_ends_the_stream_with_an_error_event():
    client = FakeClient([RuntimeError("429 rate limited")])

    events = await collect(_agentic_loop(client, [], [], None))

    assert types_of(events) == ["error"]
    assert "429 rate limited" in events[0][1]["message"]


# @verifies REQ-0007
async def test_a_stream_that_breaks_mid_answer_ends_with_an_error_event():
    client = FakeClient([[text_chunk("par"), ConnectionError("reset")]])

    events = await collect(_agentic_loop(client, [], [], None))

    assert types_of(events) == ["token", "error"]


async def test_the_last_round_is_offered_no_tools_so_an_answer_is_forced(monkeypatch):
    """A model that keeps calling tools would otherwise exhaust `MAX_TOOL_ROUNDS` and
    end the stream with no answer and no error — a turn that produced nothing.

    Withholding the tools on the final round leaves it nothing to do but answer.

    @verifies REQ-0030
    """
    monkeypatch.setattr(settings, "max_tool_rounds", 2)
    skill = ScriptedSkill()
    client = FakeClient(
        [
            [tool_chunk(call_id="c", name="do_thing", arguments="{}", finish_reason="tool_calls")],
            [text_chunk("Here is what I found.", "stop")],
        ]
    )

    events = await collect(
        _agentic_loop(client, [], [{"type": "function"}], registry_with(skill))
    )

    assert "error" not in types_of(events)
    assert ("token", "Here is what I found.") in events

    first, last = client.completions.calls
    assert "tools" in first
    assert "tools" not in last


async def test_a_single_round_budget_still_offers_its_tools(monkeypatch):
    """`MAX_TOOL_ROUNDS=1` is a deployment that wants one call, not one that wants no
    tools at all — the answer-only rule must not consume the only round there is.

    @verifies REQ-0030
    """
    monkeypatch.setattr(settings, "max_tool_rounds", 1)
    client = FakeClient([[text_chunk("hi", "stop")]])

    await collect(
        _agentic_loop(client, [], [{"type": "function"}], registry_with(ScriptedSkill()))
    )

    assert "tools" in client.completions.calls[0]


# @verifies REQ-0025
async def test_a_tool_call_with_no_registry_stops_the_loop():
    client = FakeClient(
        [[tool_chunk(call_id="c", name="do_thing", arguments="{}", finish_reason="tool_calls")]]
    )

    events = await collect(_agentic_loop(client, [], [], None))
    assert events == []


async def test_unparseable_tool_arguments_become_an_empty_dict():
    """The model occasionally emits truncated JSON. The skill is still called.

    @verifies REQ-0025
    """
    skill = ScriptedSkill()
    client = FakeClient(
        [
            [tool_chunk(call_id="c", name="do_thing", arguments="{not json", finish_reason="tool_calls")],
            [text_chunk("done", "stop")],
        ]
    )

    await collect(_agentic_loop(client, [], [{"type": "function"}], registry_with(skill)))
    assert skill.calls == [("do_thing", {})]


# ---------------------------------------------------------------------------
# stream_chat wiring
# ---------------------------------------------------------------------------


# @verifies REQ-0027
async def test_the_system_prompt_carries_every_skill_fragment(monkeypatch):

    class Fragmented(ScriptedSkill):
        def get_system_prompt_fragment(self):
            return "**Scripted**: does things."

    client = FakeClient([[text_chunk("hi", "stop")]])
    monkeypatch.setattr(openai_stream, "_client", lambda: client)

    await collect(
        stream_chat(
            user_message="hello",
            context_blocks=[],
            skill_registry=registry_with(Fragmented()),
        )
    )

    system = client.completions.calls[0]["messages"][0]
    assert system["role"] == "system"
    assert "CELINE Energy Assistant" in system["content"]
    assert "**Scripted**: does things." in system["content"]


# @verifies REQ-0027
async def test_tools_are_only_offered_when_a_registry_has_some(monkeypatch):
    client = FakeClient([[text_chunk("hi", "stop")]])
    monkeypatch.setattr(openai_stream, "_client", lambda: client)

    await collect(stream_chat(user_message="hello", context_blocks=[]))

    assert "tools" not in client.completions.calls[0]


async def test_parallel_tool_calls_are_disabled(monkeypatch):
    """The loop accumulates tool-call deltas by index but executes them in sequence and
    appends one `tool` turn each; it has never been exercised against a model that
    answers with several at once.

    @verifies REQ-0025
    """
    client = FakeClient([[text_chunk("hi", "stop")]])
    monkeypatch.setattr(openai_stream, "_client", lambda: client)

    await collect(
        stream_chat(
            user_message="hello",
            context_blocks=[],
            skill_registry=registry_with(ScriptedSkill()),
        )
    )

    assert client.completions.calls[0]["parallel_tool_calls"] is False


# @verifies REQ-0012
async def test_an_over_long_history_is_summarised_into_a_single_turn(monkeypatch):
    monkeypatch.setattr(settings, "chat_word_limit", 5)
    monkeypatch.setattr(settings, "chat_hot_messages", 2)

    summary_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="- they discussed solar"))]
    )
    client = FakeClient([summary_response, [text_chunk("ok", "stop")]])
    monkeypatch.setattr(openai_stream, "_client", lambda: client)

    history = [
        {"role": "user", "content": "one two three four"},
        {"role": "assistant", "content": "five six seven eight"},
        {"role": "user", "content": "nine ten"},
        {"role": "assistant", "content": "eleven twelve"},
    ]
    await collect(
        stream_chat(user_message="thirteen", context_blocks=[], history=history)
    )

    sent = client.completions.calls[1]["messages"]
    assert sent[1]["content"].startswith("[Summary of earlier conversation]")
    assert sent[2]["role"] == "assistant"
    # chat_hot_messages of the original turns survive verbatim.
    assert sent[-1]["content"] == "thirteen"
    assert sent[-2]["content"] == "eleven twelve"


@pytest.mark.parametrize("hot", [0, -1])
async def test_a_zero_hot_message_setting_is_floored_at_one_turn(monkeypatch, hot):
    """`[:-0]` is empty and `[-0:]` is everything, so a configured zero would summarise
    no messages and drop none of them — the opposite of what the setting reads like it
    does, and a wasted model call on top.

    At least one turn stays hot, and the rest is genuinely summarised.

    @verifies REQ-0012
    """
    monkeypatch.setattr(settings, "chat_word_limit", 1)
    monkeypatch.setattr(settings, "chat_hot_messages", hot)

    summary_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="- earlier"))]
    )
    client = FakeClient([summary_response, [text_chunk("ok", "stop")]])
    monkeypatch.setattr(openai_stream, "_client", lambda: client)

    await collect(
        stream_chat(
            user_message="four words go here",
            context_blocks=[],
            history=[{"role": "user", "content": "earlier turn"}],
        )
    )

    # The older turn was handed to the summariser rather than passed through.
    assert "earlier turn" in client.completions.calls[0]["messages"][1]["content"]

    sent = client.completions.calls[1]["messages"]
    assert sent[1]["content"].startswith("[Summary of earlier conversation]")
    assert sent[-1]["content"] == "four words go here"
