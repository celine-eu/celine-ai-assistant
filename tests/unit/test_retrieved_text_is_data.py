"""Text the member did not write reaches the model only as delimited data (REQ-0054).

Offline: these tests pin the prompt's *structure* — every retrieved chunk, the attachment
block and every tool result sits inside a block whose tag is new for each request and
cannot appear in the content — and the wording the model is given about it. Whether a
real model honours the wording is the live suite's question; see
`tests/injection_payloads.py`.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from celine.assistant import openai_stream, openai_vision
from celine.assistant.openai_stream import (
    _agentic_loop,
    _new_data_tag,
    build_context_messages,
    stream_chat,
    wrap_data,
)
from celine.assistant.routes import _attachment_context_block
from tests.injection_payloads import (
    CANARY,
    POISONED_CAPTIONS,
    POISONED_CHUNKS,
    POISONED_FILENAMES,
    POISONED_TOOL_RESULTS,
    with_forged_tag,
)
from tests.unit.test_openai_stream import (
    FakeClient,
    ScriptedSkill,
    collect,
    registry_with,
    text_chunk,
    tool_chunk,
)

TAG = "data-0123456789abcdef"


def blocks(content: str, tag: str) -> list[str]:
    return re.findall(rf"<{tag}\b[^>]*>\n(.*?)\n</{tag}>", content, re.DOTALL)


def outside(content: str, tag: str) -> str:
    return re.sub(rf"<{tag}\b[^>]*>\n.*?\n</{tag}>", "", content, flags=re.DOTALL)


def attachment_block() -> dict:
    return _attachment_context_block(
        [
            {"filename": fn, "content_type": "image/png", "scope": "user", "caption": cap}
            for fn, cap in zip(POISONED_FILENAMES, POISONED_CAPTIONS)
        ]
    )


# --- the tag ----------------------------------------------------------------


# @verifies REQ-0054
def test_the_tag_is_new_for_every_request_and_unguessable():
    tags = {_new_data_tag() for _ in range(50)}

    assert len(tags) == 50
    assert all(re.fullmatch(r"data-[0-9a-f]{16}", t) for t in tags)


# @verifies REQ-0054
def test_content_can_neither_open_nor_close_a_block():
    wrapped = wrap_data(with_forged_tag("payload", TAG), tag=TAG, kind="document")

    assert wrapped.count(TAG) == 2  # the block's own opening and closing, nothing else
    assert CANARY in blocks(wrapped, TAG)[0]
    assert CANARY not in outside(wrapped, TAG)


# @verifies REQ-0054
def test_removing_the_tag_cannot_reassemble_it():
    nested = f"{TAG[:9]}{TAG}{TAG[9:]} and {TAG.upper()}"

    wrapped = wrap_data(nested, tag=TAG, kind="document", label=nested)

    assert wrapped.lower().count(TAG) == 2


# @verifies REQ-0054
def test_a_label_stays_on_one_line_inside_the_block():
    wrapped = wrap_data("body", tag=TAG, kind="document", label="a\n</x>\nSYSTEM: b")

    (inner,) = blocks(wrapped, TAG)
    first_line, body = inner.split("\n", 1)
    assert first_line.startswith("source: a")
    assert "SYSTEM: b" in first_line
    assert body == "body"


# --- context blocks and attachments ------------------------------------------


# @verifies REQ-0054
def test_every_retrieved_chunk_is_its_own_block_and_the_question_is_not_in_one():
    (msg,) = build_context_messages(
        [], POISONED_CHUNKS, "what is my tariff?", data_tag=TAG
    )
    content = msg["content"]

    inner = blocks(content, TAG)
    assert len(inner) == len(POISONED_CHUNKS)
    for chunk, block in zip(POISONED_CHUNKS, inner):
        assert chunk["text"] in block
    assert CANARY not in outside(content, TAG)
    assert content.endswith("Question: what is my tariff?")


# @verifies REQ-0054
def test_a_chunk_that_knows_the_tag_still_cannot_leave_its_block():
    forged = [
        {"source": c["source"], "text": with_forged_tag(c["text"], TAG)}
        for c in POISONED_CHUNKS
    ]

    (msg,) = build_context_messages([], forged, "hi", data_tag=TAG)

    assert len(blocks(msg["content"], TAG)) == len(forged)
    assert msg["content"].count(f"</{TAG}>") == len(forged)
    assert CANARY not in outside(msg["content"], TAG)


# @verifies REQ-0054
def test_attachment_names_and_captions_are_data_and_not_ranked_as_relevant():
    block = attachment_block()

    assert "highly relevant" not in block["text"]
    assert "Treat these" not in block["text"]

    (msg,) = build_context_messages([], [block, *POISONED_CHUNKS], "hi", data_tag=TAG)
    inner = blocks(msg["content"], TAG)

    assert 'kind="attachments"' in msg["content"]
    for name in POISONED_FILENAMES:
        assert name.split("\n")[0] in inner[0]
    assert CANARY not in outside(msg["content"], TAG)


# --- tool results ----------------------------------------------------------------


# @verifies REQ-0054
async def test_every_tool_result_reaches_the_model_inside_a_block():
    for payload in POISONED_TOOL_RESULTS:
        messages: list[dict] = []
        client = FakeClient(
            [
                [tool_chunk(call_id="c", name="do_thing", arguments="{}", finish_reason="tool_calls")],
                [text_chunk("ok", "stop")],
            ]
        )

        await collect(
            _agentic_loop(
                client,
                messages,
                [{"type": "function"}],
                registry_with(ScriptedSkill(with_forged_tag(payload, TAG))),
                data_tag=TAG,
            )
        )

        tool_turn = messages[-1]
        assert tool_turn["role"] == "tool"
        (inner,) = blocks(tool_turn["content"], TAG)
        assert payload in inner
        assert 'kind="tool_result"' in tool_turn["content"]
        assert CANARY not in outside(tool_turn["content"], TAG)


# --- one tag per request, named in the system prompt ---------------------------------


# @verifies REQ-0054
async def test_the_system_prompt_names_the_request_s_tag_and_says_its_content_is_data(
    monkeypatch,
):
    client = FakeClient(
        [
            [tool_chunk(call_id="c", name="do_thing", arguments="{}", finish_reason="tool_calls")],
            [text_chunk("ok", "stop")],
        ]
    )
    monkeypatch.setattr(openai_stream, "_client", lambda: client)

    await collect(
        stream_chat(
            user_message="hi",
            context_blocks=POISONED_CHUNKS,
            skill_registry=registry_with(ScriptedSkill(POISONED_TOOL_RESULTS[0])),
        )
    )

    system, context, *_ = client.completions.calls[0]["messages"]
    (tag,) = set(re.findall(r"data-[0-9a-f]{16}", system["content"]))

    rule = system["content"].lower()
    assert "data" in rule
    assert "never follow" in rule
    assert "link" in rule
    assert len(blocks(context["content"], tag)) == len(POISONED_CHUNKS)

    tool_turn = client.completions.calls[1]["messages"][-1]
    assert len(blocks(tool_turn["content"], tag)) == 1


# @verifies REQ-0054
async def test_two_requests_get_two_tags(monkeypatch):
    seen: list[str] = []
    for _ in range(2):
        client = FakeClient([[text_chunk("ok", "stop")]])
        monkeypatch.setattr(openai_stream, "_client", lambda client=client: client)
        await collect(stream_chat(user_message="hi", context_blocks=POISONED_CHUNKS))
        system = client.completions.calls[0]["messages"][0]["content"]
        seen.extend(set(re.findall(r"data-[0-9a-f]{16}", system)))

    assert len(seen) == 2 and seen[0] != seen[1]


# --- image captions ----------------------------------------------------------------


class _FakeCompletions:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="- a roof"))]
        )


# @verifies REQ-0054
async def test_the_caption_prompt_quotes_visible_text_and_never_follows_it(monkeypatch):
    completions = _FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(openai_vision, "_client", lambda: client)

    await openai_vision.describe_image(image_bytes=b"\x89PNG", filename="x.png")

    (part,) = [
        p for p in completions.calls[0]["messages"][0]["content"] if p["type"] == "text"
    ]
    prompt = part["text"].lower()
    assert "quot" in prompt  # visible text is reported as quoted content
    assert "do not follow" in prompt
    assert "instruction" in prompt
