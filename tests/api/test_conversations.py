"""Conversation listing, reading and deletion — all of it scoped to the caller."""

from __future__ import annotations

from tests.conftest import OTHER_USER_ID, USER_ID


async def seed(history, user_id: str, conversation_id: str, *messages: str) -> str:
    conv = await history.get_or_create_conversation(user_id, conversation_id)
    for i, text in enumerate(messages):
        await history.append_message(
            user_id, conv.conversation_id, "user" if i % 2 == 0 else "assistant", text
        )
    return conv.conversation_id


# @verifies REQ-0010
async def test_a_listing_only_shows_the_caller_s_conversations(
    client, history, user_headers
):
    await seed(history, USER_ID, "mine", "hello")
    await seed(history, OTHER_USER_ID, "theirs", "hello")

    body = (await client.get("/conversations", headers=user_headers)).json()

    assert [c["conversation_id"] for c in body["items"]] == ["mine"]


# @verifies REQ-0010
async def test_a_listing_carries_a_snippet_and_a_count(client, history, user_headers):
    await seed(history, USER_ID, "mine", "first question", "an answer")

    (item,) = (await client.get("/conversations", headers=user_headers)).json()["items"]

    assert item["message_count"] == 2
    assert item["last_snippet"] == "an answer"


async def test_paging_bounds_are_clamped_rather_than_rejected(client, user_headers):
    """A hand-written URL with `limit=100000` is a mistake, not an attack; the route
    corrects it and reports what it used.

    @verifies REQ-0013
    """
    body = (
        await client.get(
            "/conversations?limit=100000&offset=-5", headers=user_headers
        )
    ).json()

    assert body["limit"] == 200
    assert body["offset"] == 0

    body = (await client.get("/conversations?limit=0", headers=user_headers)).json()
    assert body["limit"] == 1


# @verifies REQ-0010
async def test_messages_are_returned_in_order(client, history, user_headers):
    await seed(history, USER_ID, "mine", "one", "two", "three")

    body = (
        await client.get("/conversations/mine/messages", headers=user_headers)
    ).json()

    assert [m["content"] for m in body["messages"]] == ["one", "two", "three"]
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]


# @verifies REQ-0010
async def test_another_user_s_conversation_is_not_found(client, history, user_headers):
    await seed(history, OTHER_USER_ID, "theirs", "secret")

    r = await client.get("/conversations/theirs/messages", headers=user_headers)
    assert r.status_code == 404


# @verifies REQ-0010
async def test_an_unknown_conversation_is_not_found(client, user_headers):
    r = await client.get("/conversations/nope/messages", headers=user_headers)
    assert r.status_code == 404


async def test_a_conversation_beyond_the_listing_page_is_still_readable(
    client, history, user_headers
):
    """Existence is one indexed lookup, not a scan of the caller's recent conversations.

    The route used to page through the most recent 200 and call anything past the end
    missing, so a heavy user's older conversation became unreadable while still being
    listed.

    @verifies REQ-0010
    """
    for i in range(201):
        await seed(history, USER_ID, f"conv-{i:03d}", f"message {i}")

    oldest = "conv-000"
    listed = (
        await client.get("/conversations?limit=200", headers=user_headers)
    ).json()["items"]
    assert oldest not in [c["conversation_id"] for c in listed]

    r = await client.get(f"/conversations/{oldest}/messages", headers=user_headers)

    assert r.status_code == 200
    assert [m["content"] for m in r.json()["messages"]] == ["message 0"]


async def test_an_empty_conversation_is_readable_and_not_confused_with_a_missing_one(
    client, history, user_headers
):
    """An empty message list is what a brand-new conversation looks like, so ownership
    has to be established before the messages are read rather than inferred from them.

    @verifies REQ-0010
    """
    await history.get_or_create_conversation(USER_ID, "brand-new")

    r = await client.get("/conversations/brand-new/messages", headers=user_headers)

    assert r.status_code == 200
    assert r.json()["messages"] == []


# @verifies REQ-0013
async def test_a_message_limit_is_clamped(client, history, user_headers):
    await seed(history, USER_ID, "mine", "one")

    body = (
        await client.get("/conversations/mine/messages?limit=99999", headers=user_headers)
    ).json()
    assert body["limit"] == 500


# @verifies REQ-0011
async def test_deleting_a_conversation_removes_its_messages(
    client, history, user_headers
):
    await seed(history, USER_ID, "mine", "one")

    r = await client.delete("/conversations/mine", headers=user_headers)

    assert r.status_code == 200
    assert r.json() == {"status": "deleted", "conversation_id": "mine"}
    assert history.messages == []


async def test_deleting_someone_else_s_conversation_is_reported_as_not_found(
    client, history, user_headers, other_user_headers
):
    """404 rather than 403: a 403 would confirm the id belongs to somebody.

    @verifies REQ-0011
    """
    await seed(history, OTHER_USER_ID, "theirs", "secret")

    r = await client.delete("/conversations/theirs", headers=user_headers)

    assert r.status_code == 404
    assert (
        await client.get("/conversations/theirs/messages", headers=other_user_headers)
    ).status_code == 200
