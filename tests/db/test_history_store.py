"""`HistoryStore` against a real database.

What these cover that `FakeHistoryStore` cannot: the SQL. The conversation listing is
three correlated subqueries and an ordering; the delete is a cascade; the scoping is a
`WHERE` clause. A double reimplements the intent and therefore agrees with itself.
"""

from __future__ import annotations

import pytest

ALICE = "alice"
BOB = "bob"


async def conversation(store, user=ALICE, conversation_id=None, *messages):
    conv = await store.get_or_create_conversation(user, conversation_id)
    for i, text in enumerate(messages):
        await store.append_message(
            user, conv.conversation_id, "user" if i % 2 == 0 else "assistant", text
        )
    return conv.conversation_id


# --- conversations ----------------------------------------------------------


# @verifies REQ-0006
async def test_a_conversation_is_created_with_a_generated_id(store):
    conv = await store.get_or_create_conversation(ALICE)

    assert conv.conversation_id
    assert conv.user_id == ALICE
    assert conv.created_at > 0


# @verifies REQ-0006
async def test_an_existing_conversation_is_returned_not_duplicated(store):
    first = await store.get_or_create_conversation(ALICE, "c1")
    second = await store.get_or_create_conversation(ALICE, "c1")

    assert second.conversation_id == first.conversation_id
    assert len(await store.list_conversations(ALICE)) == 1


async def test_another_user_s_id_creates_a_separate_conversation(store):
    """The lookup is by id **and** user. Two users may hold the same id and neither can
    read the other's — which is what makes a guessed id harmless.

    @verifies REQ-0010
    """
    await store.get_or_create_conversation(ALICE, "shared-id")

    with pytest.raises(Exception):
        # Same primary key, different owner: the database refuses.
        await store.get_or_create_conversation(BOB, "shared-id")


# @verifies REQ-0010
async def test_a_listing_is_scoped_to_its_user(store):
    await conversation(store, ALICE, "mine", "hello")
    await conversation(store, BOB, "theirs", "hello")

    rows = await store.list_conversations(ALICE)

    assert [r["conversation_id"] for r in rows] == ["mine"]


async def test_a_listing_carries_the_count_and_a_snippet(store):
    """Three correlated subqueries, one per column. @verifies REQ-0010"""
    await conversation(store, ALICE, "c1", "first question", "an answer", "a follow-up")

    (row,) = await store.list_conversations(ALICE)

    assert row["message_count"] == 3
    assert row["last_snippet"]
    assert row["last_message_at"] >= row["created_at"]


async def test_the_snippet_is_not_reliably_the_last_message(store, clock):
    """`last_snippet` is `ORDER BY created_at DESC LIMIT 1`, and `created_at` is whole
    seconds — so messages written inside one second tie, and the database returns
    whichever row it likes. Which one that is depends on the engine and the plan, so
    what is asserted here is that the column named for the last message is not
    guaranteed to hold it.

    Pinned as it is. See DEFECT-16 in `.agents/plans/defect-remediation.md`; the fix is
    a schema or units change on a field the frontend reads, which is not a call to make
    from inside this repository.

    @verifies REQ-0010
    """
    await conversation(store, ALICE, "c1", "first question", "an answer", "a follow-up")

    (row,) = await store.list_conversations(ALICE)
    messages = await store.list_messages(ALICE, "c1")

    assert len({m["created_at"] for m in messages}) == 1
    assert row["last_snippet"] in {m["content"] for m in messages}


async def test_the_snippet_is_the_last_message_when_the_seconds_differ(store, clock):
    """One second apart is the finest distinction this schema can record, and with it
    the column means what it says.

    @verifies REQ-0010
    """
    await conversation(store, ALICE, "c1", "first question")
    clock.advance(2)
    await store.append_message(ALICE, "c1", "assistant", "an answer")

    (row,) = await store.list_conversations(ALICE)
    assert row["last_snippet"] == "an answer"


# @verifies REQ-0010
async def test_the_snippet_is_cut_at_a_hundred_and_twenty_characters(store):
    await conversation(store, ALICE, "c1", "x" * 500)

    (row,) = await store.list_conversations(ALICE)
    assert len(row["last_snippet"]) == 120


async def test_a_conversation_with_no_messages_still_lists(store):
    """A conversation is created before its first message is stored, so a listing that
    dropped the empty ones would lose the turn in progress.

    @verifies REQ-0010
    """
    await store.get_or_create_conversation(ALICE, "empty")

    (row,) = await store.list_conversations(ALICE)

    assert row["message_count"] == 0
    assert row["last_message_at"] is None
    assert row["last_snippet"] == ""


async def test_the_listing_order_ties_when_two_conversations_share_a_second(store, clock):
    """Ordered by last message — which is whole seconds, so two conversations touched in
    the same second sort equal and come back in whatever order the database chose.

    Pinned as it is; same cause as the snippet above. See DEFECT-16.

    @verifies REQ-0010
    """
    await conversation(store, ALICE, "old-but-busy", "a", "b", "c", "d")
    await conversation(store, ALICE, "new", "just one")

    rows = await store.list_conversations(ALICE)

    assert {r["conversation_id"] for r in rows} == {"old-but-busy", "new"}
    assert len({r["last_message_at"] for r in rows}) == 1


async def test_the_listing_orders_by_last_message_when_the_seconds_differ(store, clock):
    """With distinguishable timestamps the ordering is the intended one: most recently
    used first, regardless of which conversation is older or busier.

    @verifies REQ-0010
    """
    await conversation(store, ALICE, "old-but-busy", "a", "b", "c", "d")
    await conversation(store, ALICE, "new")

    clock.advance(2)
    await store.append_message(ALICE, "new", "user", "just one")

    rows = await store.list_conversations(ALICE)
    assert [r["conversation_id"] for r in rows] == ["new", "old-but-busy"]


# @verifies REQ-0013
async def test_paging_walks_the_listing(store):
    for i in range(5):
        await conversation(store, ALICE, f"c{i}", f"message {i}")

    first_page = await store.list_conversations(ALICE, limit=2, offset=0)
    second_page = await store.list_conversations(ALICE, limit=2, offset=2)

    assert len(first_page) == len(second_page) == 2
    assert not {r["conversation_id"] for r in first_page} & {
        r["conversation_id"] for r in second_page
    }


# --- existence --------------------------------------------------------------


# @verifies REQ-0010
async def test_existence_is_by_owner(store):
    await store.get_or_create_conversation(ALICE, "c1")

    assert await store.conversation_exists(ALICE, "c1") is True
    assert await store.conversation_exists(BOB, "c1") is False
    assert await store.conversation_exists(ALICE, "nope") is False


async def test_an_empty_conversation_still_exists(store):
    """The reason this method had to exist: message count says nothing about ownership.

    @verifies REQ-0010
    """
    await store.get_or_create_conversation(ALICE, "empty")

    assert await store.conversation_exists(ALICE, "empty") is True
    assert await store.list_messages(ALICE, "empty") == []


# --- messages ---------------------------------------------------------------


# @verifies REQ-0010
async def test_messages_come_back_in_the_order_they_were_written(store):
    await conversation(store, ALICE, "c1", "one", "two", "three")

    rows = await store.list_messages(ALICE, "c1")

    assert [m["content"] for m in rows] == ["one", "two", "three"]
    assert [m["role"] for m in rows] == ["user", "assistant", "user"]


async def test_message_timestamps_are_whole_seconds_so_a_fast_turn_ties(store, clock):
    """`created_at` is `int(time.time())` and `list_messages` orders by it, so every
    message written inside the same second sorts equal and the order the caller gets
    back is whatever the database happens to return.

    This test asserts the cause, which is deterministic, rather than the symptom, which
    is not. A chat turn writes its question and its answer seconds apart, so it is not
    reached in practice — but a replay or an import would.

    Recorded as an observation in `.agents/plans/defect-remediation.md`.

    @verifies REQ-0010
    """
    await conversation(store, ALICE, "c1", "one", "two", "three")

    stamps = {m["created_at"] for m in await store.list_messages(ALICE, "c1")}
    assert len(stamps) == 1


async def test_messages_are_scoped_to_their_user(store):
    """The conversation is already owner-checked above this, so this is the second lock
    on the same door — and the one that holds if a caller reaches `list_messages`
    directly.

    @verifies REQ-0010
    """
    await conversation(store, ALICE, "c1", "alice's message")

    assert await store.list_messages(BOB, "c1") == []


# @verifies REQ-0013
async def test_a_message_limit_is_applied(store):
    await conversation(store, ALICE, "c1", *[f"m{i}" for i in range(10)])

    assert len(await store.list_messages(ALICE, "c1", limit=3)) == 3


# --- deletion ---------------------------------------------------------------


async def test_deleting_a_conversation_takes_its_messages_with_it(store):
    """The cascade is declared on the relationship and on the foreign key. Nothing
    executed either until this test.

    @verifies REQ-0011
    """
    await conversation(store, ALICE, "c1", "one", "two")

    assert await store.delete_conversation(ALICE, "c1") is True

    assert await store.list_conversations(ALICE) == []
    assert await store.list_messages(ALICE, "c1") == []


# @verifies REQ-0011
async def test_deleting_another_user_s_conversation_does_nothing(store):
    await conversation(store, BOB, "theirs", "secret")

    assert await store.delete_conversation(ALICE, "theirs") is False
    assert len(await store.list_messages(BOB, "theirs")) == 1


# @verifies REQ-0011
async def test_deleting_an_unknown_conversation_is_false_not_an_error(store):
    assert await store.delete_conversation(ALICE, "never-existed") is False


# --- attachments ------------------------------------------------------------


async def record(store, scope="user", owner=ALICE, filename="bill.pdf", **overrides):
    payload = {
        "scope": scope,
        "owner_user_id": owner if scope == "user" else None,
        "uri": f"file:///tmp/{filename}",
        "path": f"/tmp/{filename}",
        "filename": filename,
        "content_type": "application/pdf",
        "size_bytes": 1234,
        "caption": None,
        "ocr_text": "Total due",
    }
    payload.update(overrides)
    return await store.record_attachment(**payload)


# @verifies REQ-0021
async def test_an_attachment_round_trips(store):
    att_id = await record(store)

    att = await store.get_attachment_any(att_id)

    assert att["filename"] == "bill.pdf"
    assert att["scope"] == "user"
    assert att["owner_user_id"] == ALICE
    assert att["size_bytes"] == 1234
    assert att["created_at"] > 0


async def test_a_listing_returns_own_and_system_attachments(store):
    """One `OR` across two scopes — the query most likely to be wrong in a way that
    leaks, and the one a double cannot check.

    @verifies REQ-0019
    """
    mine = await record(store, filename="mine.pdf")
    shared = await record(store, scope="system", filename="shared.pdf")
    await record(store, owner=BOB, filename="theirs.pdf")

    rows = await store.list_attachments_for_user(ALICE)

    assert {r["id"] for r in rows} == {mine, shared}


# @verifies REQ-0019
async def test_the_newest_attachment_is_listed_first(store):
    for i in range(3):
        await record(store, filename=f"f{i}.pdf")

    rows = await store.list_attachments_for_user(ALICE, limit=2)
    assert len(rows) == 2


# @verifies REQ-0020
async def test_an_unknown_attachment_is_none(store):
    assert await store.get_attachment_any("nope") is None


async def test_deleting_an_attachment_returns_what_was_deleted(store):
    """The row is returned so the caller can reach the blob it names — it has to be read
    before it is gone.

    @verifies REQ-0021
    """
    att_id = await record(store)

    deleted = await store.delete_attachment_any(att_id)

    assert deleted["path"] == "/tmp/bill.pdf"
    assert await store.get_attachment_any(att_id) is None


# @verifies REQ-0020
async def test_deleting_an_unknown_attachment_is_none_not_an_error(store):
    assert await store.delete_attachment_any("nope") is None


# --- the double, checked against the real thing -----------------------------


async def test_the_double_and_the_store_agree_on_a_conversation_listing(store):
    """`tests/unit/test_history_contract.py` checks the signatures match. This checks the
    answers do, on the query the API suite leans on hardest.

    Timestamps are excluded: the double counts messages where the store reads a clock.

    @verifies REQ-0010
    """
    from tests.conftest import FakeHistoryStore

    double = FakeHistoryStore()

    for target in (store, double):
        conv = await target.get_or_create_conversation(ALICE, "c1")
        await target.append_message(ALICE, conv.conversation_id, "user", "hello")
        await target.append_message(ALICE, conv.conversation_id, "assistant", "hi there")
        other = await target.get_or_create_conversation(BOB, "c2")
        await target.append_message(BOB, other.conversation_id, "user", "not mine")

    def comparable(rows):
        return [
            {k: r[k] for k in ("conversation_id", "message_count", "last_snippet")}
            for r in rows
        ]

    real, fake = (
        comparable(await store.list_conversations(ALICE)),
        comparable(await double.list_conversations(ALICE)),
    )

    assert [r["conversation_id"] for r in real] == [r["conversation_id"] for r in fake]
    assert [r["message_count"] for r in real] == [r["message_count"] for r in fake]


async def test_the_double_is_more_correct_than_the_store_about_the_snippet(store, clock):
    """Worth stating plainly: `FakeHistoryStore` keeps a list and reports its last entry,
    so it gets the snippet the column is named for. The store ties on whole seconds and
    does not.

    Everywhere the API suite asserts a `last_snippet`, it is asserting the double's
    answer — which is the intended one, and not yet the real one. See DEFECT-16.

    @verifies REQ-0010
    """
    from tests.conftest import FakeHistoryStore

    double = FakeHistoryStore()
    for target in (store, double):
        await conversation(target, ALICE, "c1", "first question", "an answer")

    (real,) = await store.list_conversations(ALICE)
    (fake,) = await double.list_conversations(ALICE)

    assert fake["last_snippet"] == "an answer"
    assert real["last_snippet"] in {"first question", "an answer"}


# @verifies REQ-0019
async def test_the_double_and_the_store_agree_on_attachment_visibility(store):
    from tests.conftest import FakeHistoryStore

    double = FakeHistoryStore()

    ids = []
    for target in (store, double):
        mine = await record(target, filename="mine.pdf")
        shared = await record(target, scope="system", filename="shared.pdf")
        await record(target, owner=BOB, filename="theirs.pdf")
        ids.append({mine, shared})

    assert {r["filename"] for r in await store.list_attachments_for_user(ALICE)} == {
        r["filename"] for r in await double.list_attachments_for_user(ALICE)
    }
