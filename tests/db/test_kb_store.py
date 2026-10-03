"""`KbStore`'s SQL, against the same database `tests/db/conftest.py` sets up."""

from __future__ import annotations

import pytest

from celine.assistant.kb_store import KbStore


@pytest.fixture
def kb(session_factory) -> KbStore:
    return KbStore(session_factory=session_factory)


# @verifies REQ-0043
async def test_a_source_round_trips(kb):
    src = await kb.add_source(
        community_id="example-rec",
        kind="git",
        location="https://git.example/handbook.git",
        ref="v1",
        subpath="docs",
    )

    assert await kb.get_source(src["id"]) == src
    assert src["subpath"] == "docs"
    assert src["last_synced_version"] is None


# @verifies REQ-0043
async def test_an_unknown_kind_is_refused(kb):
    with pytest.raises(ValueError):
        await kb.add_source(community_id="example-rec", kind="ftp", location="x")


# @verifies REQ-0043
async def test_sources_are_listed_per_community(kb):
    ours = await kb.add_source(community_id="example-rec", kind="dir", location="/a")
    await kb.add_source(community_id="other-rec", kind="dir", location="/b")

    assert [s["id"] for s in await kb.list_sources("example-rec")] == [ours["id"]]
    assert len(await kb.list_sources()) == 2
    assert await kb.source_communities() == ["example-rec", "other-rec"]


# @verifies REQ-0043
async def test_a_sync_is_recorded(kb):
    src = await kb.add_source(community_id="example-rec", kind="dir", location="/a")

    await kb.mark_synced(src["id"], "abc123")

    got = await kb.get_source(src["id"])
    assert got["last_synced_version"] == "abc123"
    assert got["last_synced_at"] > 0


async def test_document_versions_are_kept_per_collection(kb):
    """A new generation starts with nothing recorded, so a rebuild imports everything.

    @verifies REQ-0041
    """
    src = await kb.add_source(community_id="example-rec", kind="dir", location="/a")
    await kb.set_document_versions(src["id"], "gen-1", {"a.md": "h1", "b.md": "h2"})

    assert await kb.document_versions(src["id"], "gen-1") == {"a.md": "h1", "b.md": "h2"}
    assert await kb.document_versions(src["id"], "gen-2") == {}

    await kb.set_document_versions(src["id"], "gen-1", {"a.md": "h3"})
    assert await kb.document_versions(src["id"], "gen-1") == {"a.md": "h3"}

    await kb.forget_collection("gen-1")
    assert await kb.document_versions(src["id"], "gen-1") == {}


# @verifies REQ-0043
async def test_removing_a_source_removes_what_was_recorded_for_it(kb):
    src = await kb.add_source(community_id="example-rec", kind="dir", location="/a")
    await kb.set_document_versions(src["id"], "gen-1", {"a.md": "h1"})

    assert (await kb.remove_source(src["id"]))["id"] == src["id"]
    assert await kb.get_source(src["id"]) is None
    assert await kb.document_versions(src["id"], "gen-1") == {}
    assert await kb.remove_source(src["id"]) is None
