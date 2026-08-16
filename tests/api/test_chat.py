"""The chat route: what the client is told, in what order, and what the model is given.

`stream_chat` is replaced wholesale here — the agentic loop has its own tests in
`tests/unit/test_openai_stream.py`. What this file is about is the framing around it:
retrieval, attachment authorisation, history, and the SSE envelope.
"""

from __future__ import annotations

import json

import pytest

from celine.assistant import routes as routes_module
from tests.conftest import (
    OTHER_USER_ID,
    USER_ID,
    curated_node,
    system_node,
    user_node,
)


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the LLM with two tokens, and capture what it was asked."""
    seen: dict = {}

    async def _stream_chat(*, user_message, context_blocks, history=None, skill_registry=None):
        seen["user_message"] = user_message
        seen["context_blocks"] = context_blocks
        seen["history"] = history
        seen["skill_registry"] = skill_registry
        for token in ("Solar ", "panels."):
            yield f"event: token\ndata: {json.dumps(token)}\n\n"

    monkeypatch.setattr(routes_module, "stream_chat", _stream_chat)
    return seen


def sse(response) -> list[tuple[str, object]]:
    events = []
    for frame in response.text.split("\n\n"):
        if not frame.strip():
            continue
        head, _, body = frame.partition("\n")
        events.append(
            (head.removeprefix("event: "), json.loads(body.removeprefix("data: ")))
        )
    return events


async def chat(client, headers, **body):
    return await client.post("/chat", headers=headers, json={"message": "", **body})


# --- the envelope -----------------------------------------------------------


# @verifies REQ-0007
async def test_a_turn_is_framed_by_meta_and_done(
    client, user_headers, fake_llm, fake_retrieval
):
    r = await chat(client, user_headers, message="what is solar?")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["x-accel-buffering"] == "no"

    events = sse(r)
    assert [e for e, _ in events] == ["meta", "sources", "token", "token", "done"]
    assert events[0][1]["conversation_id"]
    assert events[-1][1] is None


# @verifies REQ-0007
async def test_citations_can_be_turned_off(
    client, user_headers, fake_llm, fake_retrieval
):
    r = await chat(client, user_headers, message="hi", include_citations=False)
    assert "sources" not in [e for e, _ in sse(r)]


# @verifies REQ-0006
async def test_a_new_conversation_is_created_and_reported(
    client, history, user_headers, fake_llm, fake_retrieval
):
    r = await chat(client, user_headers, message="hi")

    conversation_id = sse(r)[0][1]["conversation_id"]
    assert conversation_id in history.conversations


# @verifies REQ-0006
async def test_an_existing_conversation_is_continued(
    client, history, user_headers, fake_llm, fake_retrieval
):
    conv = await history.get_or_create_conversation(USER_ID, "existing")

    r = await chat(client, user_headers, message="hi", conversation_id="existing")

    assert sse(r)[0][1]["conversation_id"] == conv.conversation_id
    assert len(history.conversations) == 1


async def test_someone_else_s_conversation_id_starts_a_new_conversation(
    client, history, user_headers, fake_llm, fake_retrieval
):
    """The store's lookup is by id **and** user, so a guessed id cannot be joined — it
    quietly becomes a fresh conversation of the caller's own.

    @verifies REQ-0010
    """
    await history.get_or_create_conversation(OTHER_USER_ID, "theirs")

    r = await chat(client, user_headers, message="hi", conversation_id="theirs")

    assert sse(r)[0][1]["conversation_id"] == "theirs"
    assert history.conversations["theirs"].user_id == USER_ID


# --- persistence ------------------------------------------------------------


# @verifies REQ-0008
# @verifies REQ-0009
async def test_both_sides_of_the_turn_are_persisted(
    client, history, user_headers, fake_llm, fake_retrieval
):
    await chat(client, user_headers, message="what is solar?")

    assert [(m["role"], m["content"]) for m in history.messages] == [
        ("user", "what is solar?"),
        ("assistant", "Solar panels."),
    ]


async def test_prior_history_is_replayed_without_the_message_just_stored(
    client, history, user_headers, fake_llm, fake_retrieval
):
    """The route appends the user's turn before it reads the history back, so the last
    entry is the message it is about to answer. Sending it twice would have the model
    reply to itself.

    @verifies REQ-0012
    """
    await history.get_or_create_conversation(USER_ID, "c1")
    await history.append_message(USER_ID, "c1", "user", "earlier question")
    await history.append_message(USER_ID, "c1", "assistant", "earlier answer")

    await chat(client, user_headers, message="follow-up", conversation_id="c1")

    assert fake_llm["history"] == [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
    ]


# @verifies REQ-0009
async def test_an_empty_answer_is_not_persisted(
    client, history, user_headers, fake_retrieval, monkeypatch
):

    async def _silent(**kwargs):
        yield 'event: error\ndata: {"message": "LLM request failed"}\n\n'

    monkeypatch.setattr(routes_module, "stream_chat", _silent)

    await chat(client, user_headers, message="hi")

    assert [m["role"] for m in history.messages] == ["user"]


# --- retrieval --------------------------------------------------------------


# @verifies REQ-0022
async def test_retrieved_chunks_are_offered_as_citations(
    client, user_headers, fake_llm, fake_retrieval
):
    fake_retrieval([system_node("Solar converts light.", title="Solar", source="s1")])

    r = await chat(client, user_headers, message="what is solar?")
    sources = dict(sse(r))["sources"]

    assert [s["title"] for s in sources] == ["Solar"]


async def test_hidden_chunks_are_withheld_from_the_client_but_given_to_the_model(
    client, user_headers, fake_llm, fake_retrieval
):
    """Training material is indexed with `hidden`, because a citation of an internal
    document is not something the reader can follow. It is still context.

    @verifies REQ-0022
    """
    fake_retrieval(
        [
            system_node("Public note.", title="Public"),
            curated_node("Internal note.", title="Internal"),
        ]
    )

    r = await chat(client, user_headers, message="tell me")

    assert [s["title"] for s in dict(sse(r))["sources"]] == ["Public"]
    assert [b["title"] for b in fake_llm["context_blocks"]] == ["Public", "Internal"]


# @verifies REQ-0024
async def test_retrieval_is_skipped_for_an_empty_message(
    client, user_headers, fake_llm, fake_retrieval
):
    fake_retrieval([curated_node("never asked for", title="X")])

    r = await chat(client, user_headers, message="   ")

    assert dict(sse(r))["sources"] == []


async def test_another_member_s_upload_reaches_neither_the_client_nor_the_model(
    client, user_headers, fake_llm, fake_retrieval
):
    """One collection holds the curated corpus, shared files and every member's own
    uploads. Nothing but the scoping rule keeps the last of those apart — and until it
    existed, another member's electricity bill was retrievable, quotable and citable.

    @verifies REQ-0022
    """
    fake_retrieval(
        [
            user_node(
                "Document content for bill.pdf:\nTotal due 412 EUR",
                OTHER_USER_ID,
                title="bill.pdf",
            ),
            user_node("My own meter reading", USER_ID, title="mine.pdf"),
            system_node("The community handbook", title="Handbook"),
        ]
    )

    r = await chat(client, user_headers, message="what do you know about bills?")

    titles = [s["title"] for s in dict(sse(r))["sources"]]
    assert titles == ["mine.pdf", "Handbook"]
    assert all("412 EUR" not in b["text"] for b in fake_llm["context_blocks"])


async def test_the_caller_id_reaches_the_retriever(
    client, user_headers, fake_llm, fake_retrieval
):
    """The filter itself runs inside Qdrant, where no serviceless test can watch it.
    What is checkable is that the identity it needs was passed — on both the retriever
    and the query.

    @verifies REQ-0022
    """
    await chat(client, user_headers, message="anything")

    assert [c["user_id"] for c in fake_retrieval.calls] == [USER_ID, USER_ID]


# --- attachments ------------------------------------------------------------


async def attach(history, owner=USER_ID, scope="user", caption="A photo of a meter"):
    return await history.record_attachment(
        scope=scope,
        owner_user_id=owner if scope == "user" else None,
        uri="file:///tmp/x",
        path="/tmp/x",
        filename="meter.png",
        content_type="image/png",
        size_bytes=10,
        caption=caption,
        ocr_text=caption,
    )


async def test_an_attachment_leads_the_context(
    client, history, user_headers, fake_llm, fake_retrieval
):
    """It is put first deliberately: the user just attached it, so it outranks anything
    retrieval found.

    @verifies REQ-0023
    """
    fake_retrieval([curated_node("Background.", title="Background")])
    att_id = await attach(history)

    r = await chat(client, user_headers, message="what is this?", attachment_ids=[att_id])

    first = fake_llm["context_blocks"][0]
    assert first["source"] == "attached_files"
    assert "meter.png" in first["text"]
    assert "A photo of a meter" in first["text"]
    assert dict(sse(r))["sources"][0]["source"] == "attached_files"


async def test_an_attachment_with_no_description_says_so(
    client, history, user_headers, fake_llm, fake_retrieval
):
    """An empty description would read to the model as a file with nothing in it.

    @verifies REQ-0023
    """
    att_id = await attach(history, caption=None)

    await chat(client, user_headers, message="what is this?", attachment_ids=[att_id])

    assert "(no description available)" in fake_llm["context_blocks"][0]["text"]


# @verifies REQ-0016
async def test_attaching_someone_else_s_file_is_forbidden(
    client, history, user_headers, fake_llm, fake_retrieval
):
    att_id = await attach(history, owner=OTHER_USER_ID)

    r = await chat(client, user_headers, message="what is this?", attachment_ids=[att_id])
    assert r.status_code == 403


# @verifies REQ-0017
async def test_a_system_attachment_may_be_attached_by_anyone(
    client, history, user_headers, fake_llm, fake_retrieval
):
    att_id = await attach(history, scope="system")

    r = await chat(client, user_headers, message="what is this?", attachment_ids=[att_id])
    assert r.status_code == 200


async def test_an_unknown_attachment_id_is_ignored_rather_than_refused(
    client, user_headers, fake_llm, fake_retrieval
):
    """A stale id from a client that cached one is not worth failing the turn over.

    @verifies REQ-0020
    """
    r = await chat(client, user_headers, message="hi", attachment_ids=["gone"])

    assert r.status_code == 200
    assert fake_llm["context_blocks"] == []


async def test_attachments_alone_are_enough_to_ask_a_question(
    client, history, user_headers, fake_llm, fake_retrieval
):
    """The UI lets a file be sent with no text; the route supplies the question.

    @verifies REQ-0024
    """
    att_id = await attach(history)

    r = await chat(client, user_headers, message="", attachment_ids=[att_id])

    assert r.status_code == 200
    assert fake_llm["user_message"].startswith("Analyze the attached files")


# --- skills -----------------------------------------------------------------


async def test_the_registry_is_built_per_request_from_the_caller_s_token(
    client, user_headers, fake_llm, fake_retrieval
):
    """No token in a trusted-header request means no upstream skills — the assistant
    forwards the caller's identity and has none of its own.

    @verifies REQ-0027
    """
    await chat(client, user_headers, message="hi")
    assert set(fake_llm["skill_registry"].skills) == {"documents"}


# @verifies REQ-0027
async def test_a_verified_token_unlocks_the_upstream_skills(
    client, user_headers, fake_llm, fake_retrieval, forwarded_token
):
    await chat(client, forwarded_token(), message="hi")

    assert "digital_twin" in fake_llm["skill_registry"].skills
