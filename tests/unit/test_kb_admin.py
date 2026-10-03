"""Rebuilds, pruning and the legacy migration, end to end against an in-process Qdrant.

The stores are the doubles; the sources are directories on disk; vision and extraction
are faked where `--re-extract` would call them.
"""

from __future__ import annotations

import pytest

from celine.assistant import attachment_index, kb_admin, kb_collections, rag
from celine.assistant.settings import settings
from tests.conftest import COMMUNITY, OTHER_COMMUNITY, FakeHistoryStore, FakeKbStore


@pytest.fixture
def history() -> FakeHistoryStore:
    return FakeHistoryStore()


@pytest.fixture
def kb_store() -> FakeKbStore:
    return FakeKbStore()


@pytest.fixture
def handbook(tmp_path):
    root = tmp_path / "handbook"
    root.mkdir()
    (root / "solar.md").write_text("# Solar\n\nPanels.")
    (root / "wind.md").write_text("# Wind\n\nTurbines.")
    return root


async def attach(history, *, scope="system", owner=None, community_id=COMMUNITY, text="Total due"):
    return await history.record_attachment(
        scope=scope,
        owner_user_id=owner,
        community_id=community_id,
        uri="file:///tmp/bill.pdf",
        path="/tmp/bill.pdf",
        filename="bill.pdf",
        content_type="application/pdf",
        size_bytes=4,
        caption=None,
        ocr_text=text,
    )


def doc_ids(name: str) -> set[str]:
    return rag.indexed_values(name, "doc_id")


async def test_a_rebuild_holds_every_source_document_and_attachment(
    memory_qdrant, history, kb_store, handbook
):
    """@verifies REQ-0041"""
    src = await kb_store.add_source(community_id=COMMUNITY, kind="dir", location=str(handbook))
    att = await attach(history)
    await attach(history, community_id=OTHER_COMMUNITY)
    await attach(history, text=None)  # stored, never indexed

    result = await kb_admin.reindex(COMMUNITY, history=history, kb_store=kb_store)

    assert result["documents"] == 3
    assert doc_ids(kb_collections.alias_name(COMMUNITY)) == {
        f"source:{src['id']}:solar.md",
        f"source:{src['id']}:wind.md",
        f"attachment:{att}",
    }


async def test_a_rebuild_moves_the_alias_and_keeps_the_old_generation(
    memory_qdrant, history, kb_store
):
    """The old generation stays until `kb prune`, so a bad rebuild can be pointed back.

    @verifies REQ-0041
    """
    await attach(history)
    first = await kb_admin.reindex(COMMUNITY, history=history, kb_store=kb_store)

    second = await kb_admin.reindex(COMMUNITY, history=history, kb_store=kb_store)

    client = memory_qdrant.client
    assert second["previous"] == first["collection"]
    assert kb_collections.aliases(client)[second["alias"]] == second["collection"]
    assert set(kb_collections.generations(client)) == {first["collection"], second["collection"]}


async def test_a_failed_rebuild_leaves_the_live_knowledge_base_alone(
    memory_qdrant, history, kb_store, tmp_path
):
    """@verifies REQ-0041"""
    await attach(history)
    live = await kb_admin.reindex(COMMUNITY, history=history, kb_store=kb_store)
    await kb_store.add_source(community_id=COMMUNITY, kind="dir", location=str(tmp_path / "gone"))

    with pytest.raises(Exception, match="not a directory"):
        await kb_admin.reindex(COMMUNITY, history=history, kb_store=kb_store)

    client = memory_qdrant.client
    assert kb_collections.aliases(client)[live["alias"]] == live["collection"]
    assert kb_collections.generations(client) == [live["collection"]]


async def test_what_changed_during_a_rebuild_reaches_the_new_generation(
    memory_qdrant, history, kb_store, monkeypatch
):
    """An upload during the build went to the old generation; a delete during it left
    the document in the new one. Both are reconciled after the alias moves.

    @verifies REQ-0041
    """
    kept = await attach(history)
    doomed = await attach(history)
    late: dict = {}

    real_point_alias = kb_collections.point_alias

    def _point_alias_while_members_act(client, alias, collection):
        # Runs between the build and the switch, as a concurrent request would.
        history.attachments.pop(doomed)
        return real_point_alias(client, alias, collection)

    monkeypatch.setattr(kb_collections, "point_alias", _point_alias_while_members_act)

    original_list = history.list_attachments_for_community
    calls = {"n": 0}

    async def _list(community_id):
        calls["n"] += 1
        if calls["n"] == 2:  # the catch-up's read, after the switch
            late["id"] = await attach(history)
        return await original_list(community_id)

    monkeypatch.setattr(history, "list_attachments_for_community", _list)

    result = await kb_admin.reindex(COMMUNITY, history=history, kb_store=kb_store)

    assert result["caught_up"] == {"added": 1, "removed": 1}
    assert doc_ids(result["collection"]) == {f"attachment:{kept}", f"attachment:{late['id']}"}


async def test_re_extraction_runs_the_upload_path_again_and_stores_its_text(
    memory_qdrant, history, kb_store, monkeypatch
):
    """For when extraction itself changed. It reads the stored blob, so it costs model
    calls; without the flag the stored text is re-embedded as it is.

    @verifies REQ-0041
    """
    att = await attach(history, text="old extraction")

    async def _read_blob(path):
        return b"%PDF-1.7"

    async def _extract_text(data, mime, filename=None):
        return "new extraction"

    monkeypatch.setattr(kb_admin, "read_blob", _read_blob)
    monkeypatch.setattr(attachment_index, "extract_text", _extract_text)

    result = await kb_admin.reindex(
        COMMUNITY, history=history, kb_store=kb_store, re_extract=True
    )

    assert result["re_extracted"] == 1
    assert (await history.get_attachment_any(att))["ocr_text"] == "new extraction"


async def test_a_dry_run_builds_nothing(memory_qdrant, history, kb_store):
    """@verifies REQ-0041"""
    await attach(history)

    result = await kb_admin.reindex(COMMUNITY, history=history, kb_store=kb_store, dry_run=True)

    assert result["attachments"] == 1
    assert kb_collections.generations(memory_qdrant.client) == []


async def test_a_new_model_s_knowledge_is_built_beside_the_current_one(
    memory_qdrant, history, kb_store, monkeypatch
):
    """The deploy that changes `LLM_EMBED_MODEL` is the switch: until then the service
    keeps reading the old alias.

    @verifies REQ-0041
    """
    await attach(history)
    old = await kb_admin.reindex(COMMUNITY, history=history, kb_store=kb_store)

    monkeypatch.setattr(settings, "llm_embed_model", "the-next-model")
    monkeypatch.setattr(settings, "llm_embed_dimensions", 16)
    new = await kb_admin.reindex(COMMUNITY, history=history, kb_store=kb_store)

    client = memory_qdrant.client
    assert new["alias"] != old["alias"]
    assert new["previous"] is None
    assert kb_collections.aliases(client)[old["alias"]] == old["collection"]
    assert kb_collections.vector_size(client, new["collection"]) == 16


# --- prune ------------------------------------------------------------------


async def test_prune_deletes_only_what_no_alias_points_to(memory_qdrant, history, kb_store):
    """@verifies REQ-0041"""
    await attach(history)
    first = await kb_admin.reindex(COMMUNITY, history=history, kb_store=kb_store)
    second = await kb_admin.reindex(COMMUNITY, history=history, kb_store=kb_store)

    assert await kb_admin.prune(kb_store=kb_store, dry_run=True) == [first["collection"]]
    assert kb_collections.generations(memory_qdrant.client) == sorted(
        [first["collection"], second["collection"]]
    )

    assert await kb_admin.prune(kb_store=kb_store) == [first["collection"]]
    assert kb_collections.generations(memory_qdrant.client) == [second["collection"]]


async def test_prune_can_keep_the_newest_unaliased_generations(
    memory_qdrant, history, kb_store, monkeypatch
):
    """@verifies REQ-0041"""
    import itertools

    clock = itertools.count(1_700_000_000, 60)
    monkeypatch.setattr(kb_collections.time, "time", lambda: next(clock))
    results = [await kb_admin.reindex(COMMUNITY, history=history, kb_store=kb_store) for _ in range(3)]

    assert await kb_admin.prune(kb_store=kb_store, keep=1) == [results[0]["collection"]]


async def test_prune_leaves_the_legacy_collection_unless_asked(memory_qdrant, kb_store):
    """@verifies REQ-0042"""
    from qdrant_client.http import models as qm

    memory_qdrant.client.create_collection(
        settings.qdrant_collection,
        vectors_config=qm.VectorParams(size=8, distance=qm.Distance.COSINE),
    )

    assert await kb_admin.prune(kb_store=kb_store) == []
    assert await kb_admin.prune(kb_store=kb_store, legacy=True) == [settings.qdrant_collection]
    assert not memory_qdrant.client.collection_exists(settings.qdrant_collection)


# --- the legacy migration ---------------------------------------------------


async def test_legacy_data_is_assigned_registered_and_rebuilt(
    memory_qdrant, history, kb_store, handbook, monkeypatch
):
    """Everything from before knowledge bases were per community goes to one, and the
    old training-materials repository becomes its source — named by the leftover
    setting when not given.

    @verifies REQ-0042
    """
    monkeypatch.setattr(settings, "removed_training_materials_repo_url", str(handbook))
    monkeypatch.setattr(
        kb_admin.kb_sources, "prepare", lambda source: (handbook, "commit-1")
    )
    legacy = await attach(history, community_id=None)
    await attach(history, community_id=OTHER_COMMUNITY)

    result = await kb_admin.migrate_legacy(COMMUNITY, history=history, kb_store=kb_store)

    assert result["attachments_assigned"] == 1
    assert (await history.get_attachment_any(legacy))["community_id"] == COMMUNITY
    assert result["source_registered"]["location"] == str(handbook)
    assert result["reindex"]["documents"] == 3  # two pages and the attachment


async def test_running_the_migration_twice_registers_the_source_once(
    memory_qdrant, history, kb_store, handbook, monkeypatch
):
    """@verifies REQ-0042"""
    monkeypatch.setattr(kb_admin.kb_sources, "prepare", lambda source: (handbook, None))

    await kb_admin.migrate_legacy(COMMUNITY, history=history, kb_store=kb_store, git_url="https://git.example/h.git")
    again = await kb_admin.migrate_legacy(COMMUNITY, history=history, kb_store=kb_store, git_url="https://git.example/h.git")

    assert again["source_registered"] is None
    assert len(await kb_store.list_sources(COMMUNITY)) == 1


async def test_a_migration_dry_run_changes_nothing(memory_qdrant, history, kb_store):
    """@verifies REQ-0042"""
    await attach(history, community_id=None)

    result = await kb_admin.migrate_legacy(
        COMMUNITY, history=history, kb_store=kb_store, git_url="https://git.example/h.git", dry_run=True
    )

    assert result["attachments_to_assign"] == 1
    assert result["source_to_register"] == "https://git.example/h.git"
    assert await history.count_attachments_without_community() == 1
    assert await kb_store.list_sources() == []


# --- status -----------------------------------------------------------------


async def test_status_reports_each_community_and_what_needs_attention(
    memory_qdrant, history, kb_store
):
    """@verifies REQ-0041"""
    await attach(history)
    await attach(history, community_id=None)
    await kb_store.add_source(community_id=OTHER_COMMUNITY, kind="dir", location="/srv/x")
    built = await kb_admin.reindex(COMMUNITY, history=history, kb_store=kb_store)

    report = await kb_admin.status(history, kb_store)

    rows = {r["community_id"]: r for r in report["communities"]}
    assert rows[COMMUNITY]["collection"] == built["collection"]
    assert rows[COMMUNITY]["points"] >= 1
    assert rows[OTHER_COMMUNITY]["collection"] is None
    assert len(rows[OTHER_COMMUNITY]["sources"]) == 1
    assert report["attachments_without_community"] == 1
    assert report["legacy_collection"] is None
