"""Erasure, retention and the orphan sweep, end to end against an in-process Qdrant.

The vectors sit where production puts them: two generations of a community's knowledge
base, one built for another embedding model, and the collection used before knowledge
bases were per community. The history store is the double; its SQL is tested in
`tests/db/test_history_erasure.py`. Files are real, under `tmp_path`.
"""

from __future__ import annotations

import pytest
from qdrant_client.http import models as qm

from celine.assistant import erasure, kb_collections, rag
from celine.assistant.settings import settings
from celine.assistant.uploads import store_upload
from tests.conftest import COMMUNITY, OTHER_COMMUNITY, FakeHistoryStore

ALICE = "alice"
BOB = "bob"
DAY = 86_400
NOW = 1_800_000_000  # 2027-01-15


@pytest.fixture
def history() -> FakeHistoryStore:
    return FakeHistoryStore()


@pytest.fixture
def files(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "uploads_uri", f"file://{tmp_path}")
    return tmp_path


@pytest.fixture
def collections(memory_qdrant):
    """Every place a vector can be: the live generation, an older one, one for another
    embedding model, another community's, and the legacy collection."""
    client = memory_qdrant.client
    old = kb_collections.create_generation(client, COMMUNITY)
    kb_collections.ensure_alias(client, COMMUNITY)
    live = kb_collections.aliases(client)[kb_collections.alias_name(COMMUNITY)]
    assert live != old
    other_model = kb_collections.alias_name(COMMUNITY, "0123456789") + "__20250101000000"
    other_community = kb_collections.create_generation(client, OTHER_COMMUNITY)
    for name in (other_model, settings.qdrant_collection):
        client.create_collection(
            collection_name=name,
            vectors_config=qm.VectorParams(
                size=settings.llm_embed_dimensions, distance=qm.Distance.COSINE
            ),
        )
    return {
        "live": live,
        "old": old,
        "other_model": other_model,
        "other_community": other_community,
        "legacy": settings.qdrant_collection,
    }


async def upload(history, *, owner=ALICE, scope="user", community_id=COMMUNITY):
    stored = await store_upload(
        scope=scope,
        owner_user_id=owner if scope == "user" else None,
        filename="bill.pdf",
        content_type="application/pdf",
        data=b"%PDF-1.4",
    )
    att_id = await history.record_attachment(
        scope=scope,
        owner_user_id=owner if scope == "user" else None,
        community_id=community_id,
        uri=stored.uri,
        path=stored.path,
        filename=stored.filename,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        ocr_text="Total due",
    )
    return await history.get_attachment_any(att_id)


async def index(att, *names, **extra):
    meta = {
        "attachment_id": att["id"],
        "scope": att["scope"],
        "owner_user_id": att["owner_user_id"],
        **extra,
    }
    for name in names:
        await rag.upsert_documents_from_text(
            community_id=att["community_id"] or COMMUNITY,
            text="Total due",
            metadata=meta,
            doc_id=rag.attachment_doc_id(att["id"]),
            collection=name,
        )


def count(name, **match):
    return rag.count_matching(name, match)


# --- rag ---------------------------------------------------------------------------


# @verifies REQ-0056
def test_every_collection_this_service_writes_is_erasable(collections):
    assert sorted(rag.erasable_collections()) == sorted(collections.values())


# @verifies REQ-0056
def test_no_legacy_collection_is_not_an_error(memory_qdrant):
    assert rag.erasable_collections() == []
    assert rag.delete_everywhere({"attachment_id": "x"}) == {}


# --- REQ-0056: one attachment ------------------------------------------------------


# @verifies REQ-0056
async def test_an_attachment_s_vectors_go_from_every_generation_and_model(
    collections, history, files
):
    att = await upload(history)
    keep = await upload(history)
    await index(att, collections["live"], collections["old"], collections["other_model"])
    await index(keep, collections["live"])

    removed = await erasure.delete_attachment(history, att)

    assert removed == {"vectors": 3, "files": 1}
    for name in collections.values():
        assert count(name, attachment_id=att["id"]) == 0
    assert count(collections["live"], attachment_id=keep["id"]) == 1
    assert await history.get_attachment_any(att["id"]) is None
    assert not (files / att["path"].split(str(files) + "/", 1)[1]).exists()


# @verifies REQ-0056
async def test_a_row_without_a_community_loses_its_legacy_vectors(
    collections, history, files
):
    att = await upload(history, community_id=None)
    await index(att, collections["legacy"])

    removed = await erasure.delete_attachment(history, att)

    assert removed["vectors"] == 1
    assert count(collections["legacy"], attachment_id=att["id"]) == 0


# @verifies REQ-0056
async def test_a_failed_vector_delete_keeps_the_row_and_the_file(
    collections, history, files, monkeypatch
):
    att = await upload(history)
    await index(att, collections["live"])

    real = rag.delete_everywhere
    down = True

    def _flaky(*args, **kwargs):
        if down:
            raise RuntimeError("qdrant unreachable")
        return real(*args, **kwargs)

    monkeypatch.setattr(rag, "delete_everywhere", _flaky)

    with pytest.raises(erasure.AttachmentNotDeleted):
        await erasure.delete_attachment(history, att)

    assert await history.get_attachment_any(att["id"]) is not None
    assert (files / att["path"].split(str(files) + "/", 1)[1]).exists()

    down = False  # the retry, once the store is back
    assert (await erasure.delete_attachment(history, att))["vectors"] == 1


# @verifies REQ-0056
async def test_a_process_that_cannot_see_the_files_deletes_nothing(
    collections, history, files, monkeypatch, tmp_path
):
    """The operator pod has no volume: there, every file looks already deleted, and the
    delete would drop the row and leave the file. It refuses instead."""
    att = await upload(history)
    await index(att, collections["live"])
    monkeypatch.setattr(settings, "uploads_uri", f"file://{tmp_path}/not-mounted")

    with pytest.raises(erasure.AttachmentNotDeleted):
        await erasure.delete_attachment(history, att)

    assert await history.get_attachment_any(att["id"]) is not None
    assert count(collections["live"], attachment_id=att["id"]) == 1


# @verifies REQ-0056
async def test_deleting_again_is_harmless(collections, history, files):
    att = await upload(history)
    await index(att, collections["live"])
    await erasure.delete_attachment(history, att)

    assert await erasure.delete_attachment(history, att) == {"vectors": 0, "files": 0}


# --- REQ-0057: a person ------------------------------------------------------------


# @verifies REQ-0057
async def test_a_person_is_erased_from_every_store(collections, history, files):
    own = await upload(history)
    shared = await upload(history, scope="system")
    bobs = await upload(history, owner=BOB)
    await index(own, collections["live"], collections["old"])
    await index(shared, collections["live"])
    await index(bobs, collections["live"])
    # A vector of the person's whose row is already gone, and a legacy one with no scope.
    await rag.upsert_documents_from_text(
        community_id=COMMUNITY,
        text="stray",
        metadata={"attachment_id": "gone", "scope": "user", "owner_user_id": ALICE},
        doc_id="attachment:gone",
        collection=collections["other_model"],
    )
    await rag.upsert_documents_from_text(
        community_id=COMMUNITY,
        text="legacy",
        metadata={"attachment_id": "old", "owner_user_id": ALICE},
        doc_id="attachment:old",
        collection=collections["legacy"],
    )
    conv = await history.get_or_create_conversation(ALICE)
    await history.append_message(ALICE, conv.conversation_id, "user", "q")
    await history.append_message(
        ALICE, conv.conversation_id, "assistant", "a", trace={"attachments": [own["id"]]}
    )
    bob_conv = await history.get_or_create_conversation(BOB)
    await history.append_message(BOB, bob_conv.conversation_id, "user", "q")

    report = await erasure.erase_subject(history, ALICE)

    assert report == {
        "conversations": 1,
        "messages": 2,
        "attachments": 1,
        "files": 1,
        "vectors": 4,
        "failed": [],
    }
    assert await history.list_conversations(ALICE) == []
    assert await history.get_attachment_any(own["id"]) is None
    for name in collections.values():
        assert count(name, owner_user_id=ALICE) == 0
    # What was not the person's is all still there.
    assert await history.get_attachment_any(shared["id"]) is not None
    assert count(collections["live"], attachment_id=shared["id"]) == 1
    assert count(collections["live"], attachment_id=bobs["id"]) == 1
    assert len(await history.list_conversations(BOB)) == 1


# @verifies REQ-0057
async def test_erasing_twice_succeeds_and_removes_nothing(collections, history, files):
    own = await upload(history)
    await index(own, collections["live"])
    await erasure.erase_subject(history, ALICE)

    assert await erasure.erase_subject(history, ALICE) == {
        "conversations": 0,
        "messages": 0,
        "attachments": 0,
        "files": 0,
        "vectors": 0,
        "failed": [],
    }


# @verifies REQ-0057
async def test_an_attachment_that_cannot_be_deleted_is_reported_and_the_rest_goes_on(
    collections, history, files, monkeypatch
):
    stuck = await upload(history)
    other = await upload(history)
    real = erasure.delete_attachment

    async def _flaky(history_, att):
        if att["id"] == stuck["id"]:
            raise erasure.AttachmentNotDeleted(att["id"])
        return await real(history_, att)

    monkeypatch.setattr(erasure, "delete_attachment", _flaky)

    report = await erasure.erase_subject(history, ALICE)

    assert report["failed"] == [stuck["id"]]
    assert report["attachments"] == 1
    assert await history.get_attachment_any(other["id"]) is None
    assert await history.get_attachment_any(stuck["id"]) is not None


# --- REQ-0058: retention -----------------------------------------------------------


def test_the_cut_off_is_the_same_calendar_date_months_back():
    # A month back from the 31st is the last day of the shorter month.
    assert erasure.months_before(NOW, 12) == NOW - 365 * DAY
    march_31 = 1_806_451_200  # 2027-03-31T00:00:00Z
    feb_28 = 1_803_772_800  # 2027-02-28T00:00:00Z
    assert erasure.months_before(march_31, 1) == feb_28


async def _aged(history, att_or_conv_id, *, days_ago):
    """Backdate a row in the double: its `created_at` is what the SQL compares."""
    if att_or_conv_id in history.attachments:
        history.attachments[att_or_conv_id]["created_at"] = NOW - days_ago * DAY
    else:
        history.conversations[att_or_conv_id].created_at = NOW - days_ago * DAY
        for m in history.messages:
            if m["conversation_id"] == att_or_conv_id:
                m["created_at"] = NOW - days_ago * DAY


# @verifies REQ-0058
async def test_retention_deletes_what_has_been_idle_for_the_period(
    collections, history, files
):
    old_conv = (await history.get_or_create_conversation(ALICE)).conversation_id
    await history.append_message(ALICE, old_conv, "user", "q")
    await _aged(history, old_conv, days_ago=400)
    new_conv = (await history.get_or_create_conversation(ALICE)).conversation_id
    await history.append_message(ALICE, new_conv, "user", "q")
    await _aged(history, new_conv, days_ago=10)
    idle = await upload(history)
    await index(idle, collections["live"], collections["old"])
    await _aged(history, idle["id"], days_ago=400)
    recent = await upload(history)
    await _aged(history, recent["id"], days_ago=10)
    shared = await upload(history, scope="system")
    await _aged(history, shared["id"], days_ago=900)

    dry = await erasure.run_retention(history, months=12, now=NOW, dry_run=True)
    assert (dry["conversations"], dry["attachments"], dry["dry_run"]) == (1, 1, True)
    assert await history.get_attachment_any(idle["id"]) is not None

    report = await erasure.run_retention(history, months=12, now=NOW)

    assert report["cutoff"] == "2026-01-15T08:00:00+00:00"
    assert (report["conversations"], report["messages"]) == (1, 1)
    assert (report["attachments"], report["vectors"], report["failed"]) == (1, 2, [])
    assert [c["conversation_id"] for c in await history.list_conversations(ALICE)] == [
        new_conv
    ]
    assert await history.get_attachment_any(idle["id"]) is None
    assert await history.get_attachment_any(recent["id"]) is not None
    assert await history.get_attachment_any(shared["id"]) is not None


# @verifies REQ-0058
async def test_the_period_comes_from_the_setting(collections, history, files, monkeypatch):
    monkeypatch.setattr(settings, "retention_months", 1)
    att = await upload(history)
    await _aged(history, att["id"], days_ago=40)

    assert (await erasure.run_retention(history, now=NOW))["attachments"] == 1


# @verifies REQ-0058
async def test_a_period_under_one_month_is_refused(history):
    with pytest.raises(ValueError):
        await erasure.run_retention(history, months=0, now=NOW)


# --- REQ-0059: orphans -------------------------------------------------------------


# @verifies REQ-0059
async def test_vectors_without_a_row_are_listed_then_deleted(collections, history, files):
    kept = await upload(history)
    await index(kept, collections["live"])
    gone = await upload(history)
    await index(gone, collections["live"], collections["legacy"])
    history.attachments.pop(gone["id"])  # what a logged, swallowed delete failure left

    listed = await erasure.orphan_vectors(history)

    assert listed == {
        "orphans": {
            collections["live"]: {gone["id"]: 1},
            collections["legacy"]: {gone["id"]: 1},
        },
        "vectors": 2,
        "deleted": 0,
    }
    assert count(collections["live"], attachment_id=gone["id"]) == 1

    deleted = await erasure.orphan_vectors(history, delete=True)

    assert deleted["deleted"] == 2
    for name in collections.values():
        assert count(name, attachment_id=gone["id"]) == 0
    assert count(collections["live"], attachment_id=kept["id"]) == 1
    assert (await erasure.orphan_vectors(history))["vectors"] == 0
