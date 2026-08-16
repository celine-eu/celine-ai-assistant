"""The documents skill — the model's own way into the knowledge base.

Everything the chat route retrieves, the model can also retrieve for itself by calling
`search_documents`. The two paths scope retrieval separately, which is why both are
tested for it separately.
"""

from __future__ import annotations

import json

from celine.assistant.skills.documents import DocumentSkill
from tests.conftest import curated_node, user_node


def build(history) -> DocumentSkill:
    return DocumentSkill(history_store=history, user_id="alice")


async def run(skill, tool, **args) -> dict:
    return json.loads(await skill.execute(tool, args))


# --- attachment lookup ------------------------------------------------------


async def record(history, **overrides) -> str:
    payload = {
        "scope": "user",
        "owner_user_id": "alice",
        "uri": "file:///tmp/x",
        "path": "/tmp/x",
        "filename": "bill.pdf",
        "content_type": "application/pdf",
        "size_bytes": 12,
        "caption": None,
        "ocr_text": "Total due: 42 EUR",
    }
    payload.update(overrides)
    return await history.record_attachment(**payload)


# @verifies REQ-0016
async def test_the_owner_can_read_their_own_attachment(history):
    att_id = await record(history)

    result = await run(build(history), "get_attachment_info", attachment_id=att_id)

    assert result["filename"] == "bill.pdf"
    assert result["ocr_text"] == "Total due: 42 EUR"


async def test_another_user_s_attachment_is_reported_as_missing_not_forbidden(history):
    """"Not found" and "not yours" are the same sentence on purpose: the model relays
    tool output to the user, so a "forbidden" would confirm the id exists.

    @verifies REQ-0016
    """
    att_id = await record(history, owner_user_id="bob")

    assert await run(build(history), "get_attachment_info", attachment_id=att_id) == {
        "error": "Attachment not found."
    }


# @verifies REQ-0017
async def test_a_system_attachment_is_readable_by_anyone(history):
    att_id = await record(history, scope="system", owner_user_id=None)

    result = await run(build(history), "get_attachment_info", attachment_id=att_id)
    assert result["scope"] == "system"


# @verifies REQ-0020
async def test_an_unknown_attachment_id_is_an_error_not_a_crash(history):
    assert await run(build(history), "get_attachment_info", attachment_id="nope") == {
        "error": "Attachment not found."
    }


# @verifies REQ-0030
async def test_extracted_text_is_capped_before_it_reaches_the_model(history):
    att_id = await record(history, ocr_text="z" * 9000)

    result = await run(build(history), "get_attachment_info", attachment_id=att_id)
    assert len(result["ocr_text"]) == 4000


# @verifies REQ-0021
async def test_an_attachment_with_no_extracted_text_reports_none(history):
    att_id = await record(history, ocr_text=None)

    result = await run(build(history), "get_attachment_info", attachment_id=att_id)
    assert result["ocr_text"] is None


# --- search -----------------------------------------------------------------


# @verifies REQ-0022
async def test_search_returns_the_retrieved_snippets(history, fake_retrieval):
    fake_retrieval([curated_node("Solar panels convert light.", title="Solar", source="s")])

    result = await run(build(history), "search_documents", query="solar", top_k=5)

    assert result["query"] == "solar"
    assert result["results"][0]["title"] == "Solar"
    assert result["results"][0]["score"] == 0.5


# @verifies REQ-0030
async def test_a_snippet_is_capped_at_two_thousand_characters(history, fake_retrieval):
    fake_retrieval([curated_node("y" * 5000, title="Long")])

    result = await run(build(history), "search_documents", query="long")
    assert len(result["results"][0]["text"]) == 2000


async def test_search_is_scoped_to_the_calling_user(history, fake_retrieval):
    """The model can search the knowledge base for itself, so this path needs the same
    scoping as the chat route's — it is the easier of the two to forget, because the
    retrieval call is behind a function-level import.

    @verifies REQ-0022
    """
    fake_retrieval(
        [
            user_node("Bob's electricity bill: 412 EUR", "bob", title="bill.pdf"),
            user_node("Alice's own notes", "alice", title="notes.pdf"),
            curated_node("How sharing works", title="Sharing"),
        ]
    )

    result = await run(build(history), "search_documents", query="bill")

    assert [r["title"] for r in result["results"]] == ["notes.pdf", "Sharing"]


async def test_the_search_carries_the_caller_id_to_the_retriever(history, fake_retrieval):
    """Belt as well as braces: the filter runs inside Qdrant, so no serviceless test can
    prove it was applied — what can be checked is that the id reached it.

    @verifies REQ-0022
    """
    await run(build(history), "search_documents", query="anything")

    assert {c["user_id"] for c in fake_retrieval.calls} == {"alice"}


# @verifies REQ-0028
async def test_a_failing_retrieval_is_a_tool_error_not_an_exception(history, monkeypatch):
    import celine.assistant.rag as rag_mod

    def boom(top_k=5, *, user_id=None):
        raise RuntimeError("qdrant unreachable")

    monkeypatch.setattr(rag_mod, "build_retriever", boom)

    assert await run(build(history), "search_documents", query="x") == {
        "error": "qdrant unreachable"
    }


async def test_a_missing_required_argument_is_a_tool_error(history):
    """The model supplies these; a missing one must come back as something it can read.

    @verifies REQ-0025
    """
    result = await run(build(history), "search_documents")
    assert result == {"error": "'query'"}
