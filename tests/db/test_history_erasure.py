"""The queries behind erasure and retention, against a real database.

What a person owns, what has gone idle and which attachment ids still have a row are
`WHERE` clauses and a scan of stored traces; the double in `tests/conftest.py`
reimplements them, so the SQL is checked here.
"""

from __future__ import annotations

ALICE = "alice"
BOB = "bob"
COMMUNITY = "example-rec"
DAY = 86_400


async def attach(store, *, owner=ALICE, scope="user"):
    return await store.record_attachment(
        scope=scope,
        owner_user_id=owner if scope == "user" else None,
        community_id=COMMUNITY,
        uri="file:///tmp/f",
        path="/tmp/f",
        filename="f.pdf",
        content_type="application/pdf",
        size_bytes=1,
    )


async def say(store, user, conversation_id, role="user", content="hi", trace=None):
    conv = await store.get_or_create_conversation(user, conversation_id)
    await store.append_message(user, conv.conversation_id, role, content, trace=trace)
    return conv.conversation_id


# --- a person's own rows -------------------------------------------------------


# @verifies REQ-0057
async def test_a_person_s_conversations_and_messages_are_deleted_and_counted(store):
    await say(store, ALICE, "a1")
    await say(store, ALICE, "a1", role="assistant", trace={"attachments": []})
    await say(store, ALICE, "a2")
    await say(store, BOB, "b1")

    removed = await store.delete_conversations_of(ALICE)

    assert removed == {"conversations": 2, "messages": 3}
    assert await store.list_conversations(ALICE) == []
    assert [c["conversation_id"] for c in await store.list_conversations(BOB)] == ["b1"]
    assert len(await store.list_messages(BOB, "b1")) == 1


# @verifies REQ-0057
async def test_deleting_a_person_twice_removes_nothing_the_second_time(store):
    await say(store, ALICE, "a1")
    await store.delete_conversations_of(ALICE)

    assert await store.delete_conversations_of(ALICE) == {
        "conversations": 0,
        "messages": 0,
    }


# @verifies REQ-0057
async def test_a_person_s_attachments_are_their_own_uploads_only(store):
    own = await attach(store)
    await attach(store, owner=BOB)
    await attach(store, scope="system")

    assert [a["id"] for a in await store.attachments_owned_by(ALICE)] == [own]


# --- retention -------------------------------------------------------------------


# @verifies REQ-0058
async def test_a_conversation_goes_idle_by_its_newest_message(store, clock):
    await say(store, ALICE, "old")
    await say(store, ALICE, "revived")
    clock.advance(400 * DAY)
    await say(store, ALICE, "revived")
    await store.get_or_create_conversation(ALICE, "empty-new")
    cutoff = int(clock.now) - 365 * DAY

    would = await store.delete_idle_conversations(cutoff, dry_run=True)
    assert would == {"conversations": 1, "messages": 1}
    assert len(await store.list_conversations(ALICE)) == 3

    assert await store.delete_idle_conversations(cutoff) == would
    assert sorted(c["conversation_id"] for c in await store.list_conversations(ALICE)) == [
        "empty-new",
        "revived",
    ]


# @verifies REQ-0058
async def test_an_empty_conversation_goes_idle_by_its_creation(store, clock):
    await store.get_or_create_conversation(ALICE, "empty-old")
    clock.advance(400 * DAY)

    removed = await store.delete_idle_conversations(int(clock.now) - 365 * DAY)

    assert removed == {"conversations": 1, "messages": 0}


# @verifies REQ-0058
async def test_an_attachment_is_idle_unless_a_recent_answer_used_it(store, clock):
    attached = await attach(store)
    retrieved = await attach(store)
    unused = await attach(store)
    used_by_someone_else = await attach(store)
    await attach(store, scope="system")
    clock.advance(400 * DAY)
    fresh = await attach(store)
    await say(
        store,
        ALICE,
        "c",
        role="assistant",
        trace={
            "attachments": [attached],
            "sources": [{"source": "x", "attachment_id": retrieved}],
        },
    )
    await say(store, BOB, "d", role="assistant", trace={"attachments": [used_by_someone_else]})

    idle = await store.idle_attachments(int(clock.now) - 365 * DAY)

    assert sorted(a["id"] for a in idle) == sorted([unused, used_by_someone_else])
    assert fresh not in {a["id"] for a in idle}


# @verifies REQ-0058
async def test_an_old_use_does_not_keep_an_attachment(store, clock):
    att = await attach(store)
    await say(store, ALICE, "c", role="assistant", trace={"attachments": [att]})
    clock.advance(400 * DAY)

    assert [a["id"] for a in await store.idle_attachments(int(clock.now) - 365 * DAY)] == [att]


# --- orphans -----------------------------------------------------------------------


# @verifies REQ-0059
async def test_which_attachment_ids_still_have_a_row(store):
    kept = await attach(store)

    assert await store.existing_attachment_ids([kept, "gone", "also-gone"]) == {kept}
    assert await store.existing_attachment_ids([]) == set()
