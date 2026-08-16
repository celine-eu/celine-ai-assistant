"""Who may read, list and delete an attachment.

Two scopes exist — `user` and `system` — and the rules differ per verb, which is why
this is a matrix rather than a helper.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from celine.assistant import routes as routes_module
from tests.conftest import ADMIN_ID, OTHER_USER_ID, USER_ID


async def make_attachment(history, scope="user", owner=USER_ID, **overrides) -> str:
    payload = {
        "scope": scope,
        "owner_user_id": owner if scope == "user" else None,
        "uri": "file:///tmp/bill.pdf",
        "path": "/tmp/bill.pdf",
        "filename": "bill.pdf",
        "content_type": "application/pdf",
        "size_bytes": 4,
        "caption": None,
        "ocr_text": "Total due",
    }
    payload.update(overrides)
    return await history.record_attachment(**payload)


@pytest.fixture
def readable_blob(monkeypatch):
    monkeypatch.setattr(
        routes_module, "open_upload_stream", lambda path, **kw: iter([b"PDF-BYTES"])
    )


# --- listing ----------------------------------------------------------------


# @verifies REQ-0019
async def test_a_listing_shows_own_and_system_attachments(client, history, user_headers):
    mine = await make_attachment(history)
    shared = await make_attachment(history, scope="system")
    await make_attachment(history, owner=OTHER_USER_ID)

    body = (await client.get("/attachments", headers=user_headers)).json()

    assert {a["id"] for a in body["items"]} == {mine, shared}


# --- reading ----------------------------------------------------------------


# @verifies REQ-0016
async def test_the_owner_can_read_their_attachment(
    client, history, user_headers, readable_blob
):
    att_id = await make_attachment(history)

    r = await client.get(f"/attachments/{att_id}/raw", headers=user_headers)

    assert r.status_code == 200
    assert r.content == b"PDF-BYTES"
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.headers["content-disposition"] == 'inline; filename="bill.pdf"'


# @verifies REQ-0016
async def test_another_user_cannot_read_it(client, history, other_user_headers):
    att_id = await make_attachment(history)

    r = await client.get(f"/attachments/{att_id}/raw", headers=other_user_headers)
    assert r.status_code == 403


async def test_an_admin_can_read_anyone_s_attachment(
    client, history, admin_headers, readable_blob
):
    """Support needs it, and the audit trail for it is the access log.

    @verifies REQ-0016
    """
    att_id = await make_attachment(history)

    r = await client.get(f"/attachments/{att_id}/raw", headers=admin_headers)
    assert r.status_code == 200


# @verifies REQ-0017
async def test_a_system_attachment_is_readable_by_any_member(
    client, history, other_user_headers, readable_blob
):
    att_id = await make_attachment(history, scope="system")

    r = await client.get(f"/attachments/{att_id}/raw", headers=other_user_headers)
    assert r.status_code == 200


# @verifies REQ-0020
async def test_reading_an_unknown_attachment_is_not_found(client, user_headers):
    r = await client.get("/attachments/nope/raw", headers=user_headers)
    assert r.status_code == 404


async def test_an_unrecognised_scope_is_an_internal_error(
    client, history, user_headers
):
    """Neither `user` nor `system` means the row is not one this code wrote. It refuses
    rather than guessing — a 500 here is a data-integrity signal, not a bug.

    @verifies REQ-0016
    """
    att_id = await make_attachment(history, scope="team")

    r = await client.get(f"/attachments/{att_id}/raw", headers=user_headers)
    assert r.status_code == 500


# --- deleting ---------------------------------------------------------------


@pytest.fixture
def deletable_blob(monkeypatch):
    """Records the blob paths deleted, and the document ids deleted from the index."""
    deleted: list[str] = []
    unindexed: list[str] = []

    async def _delete(path: str) -> None:
        deleted.append(path)

    async def _delete_document(doc_id: str) -> None:
        unindexed.append(doc_id)

    monkeypatch.setattr(routes_module, "delete_upload", _delete)
    monkeypatch.setattr(routes_module, "delete_document", _delete_document)
    return SimpleNamespace(blobs=deleted, documents=unindexed)


# @verifies REQ-0016
async def test_the_owner_can_delete_their_attachment(
    client, history, user_headers, deletable_blob
):
    att_id = await make_attachment(history)

    r = await client.delete(f"/attachments/{att_id}", headers=user_headers)

    assert r.status_code == 200
    assert await history.get_attachment_any(att_id) is None
    assert deletable_blob.blobs == ["/tmp/bill.pdf"]


# @verifies REQ-0016
async def test_another_user_cannot_delete_it(
    client, history, other_user_headers, deletable_blob
):
    att_id = await make_attachment(history)

    r = await client.delete(f"/attachments/{att_id}", headers=other_user_headers)

    assert r.status_code == 403
    assert await history.get_attachment_any(att_id) is not None


# @verifies REQ-0018
async def test_only_an_admin_may_delete_a_system_attachment(
    client, history, user_headers, admin_headers, deletable_blob
):
    att_id = await make_attachment(history, scope="system")

    assert (
        await client.delete(f"/attachments/{att_id}", headers=user_headers)
    ).status_code == 403
    assert (
        await client.delete(f"/attachments/{att_id}", headers=admin_headers)
    ).status_code == 200


async def test_the_row_is_removed_even_when_the_blob_will_not_delete(
    client, history, user_headers, monkeypatch
):
    """Storage may be gone, read-only or simply wrong; leaving an unreachable row
    behind would be worse than an orphaned blob.

    @verifies REQ-0016
    """

    async def _explode(path: str) -> None:
        raise OSError("read-only filesystem")

    async def _delete_document(doc_id: str) -> None:
        return None

    monkeypatch.setattr(routes_module, "delete_upload", _explode)
    monkeypatch.setattr(routes_module, "delete_document", _delete_document)
    att_id = await make_attachment(history)

    r = await client.delete(f"/attachments/{att_id}", headers=user_headers)

    assert r.status_code == 200
    assert await history.get_attachment_any(att_id) is None


# @verifies REQ-0020
async def test_deleting_an_unknown_attachment_is_not_found(client, user_headers):
    r = await client.delete("/attachments/nope", headers=user_headers)
    assert r.status_code == 404


async def test_deleting_an_attachment_also_removes_it_from_the_index(
    client, history, user_headers, deletable_blob
):
    """An attachment is three things: a row, a blob, and a document in the vector store.
    Leaving the last one behind meant deleted content stayed retrievable and quotable
    for as long as the collection did — which is not a deletion.

    @verifies REQ-0021 @verifies REQ-0022
    """
    att_id = await make_attachment(history)

    await client.delete(f"/attachments/{att_id}", headers=user_headers)

    assert deletable_blob.documents == [f"attachment:{att_id}"]


async def test_the_row_is_removed_even_when_the_index_will_not_delete(
    client, history, user_headers, monkeypatch
):
    """Qdrant being unreachable must not strand the attachment as undeletable. The
    failure is logged; what is owed afterwards is a reindex, not a retry the caller has
    to drive.

    @verifies REQ-0021
    """

    async def _explode(doc_id: str) -> None:
        raise RuntimeError("qdrant unreachable")

    async def _delete_blob(path: str) -> None:
        return None

    monkeypatch.setattr(routes_module, "delete_document", _explode)
    monkeypatch.setattr(routes_module, "delete_upload", _delete_blob)
    att_id = await make_attachment(history)

    r = await client.delete(f"/attachments/{att_id}", headers=user_headers)

    assert r.status_code == 200
    assert await history.get_attachment_any(att_id) is None


# @verifies REQ-0018
async def test_an_admin_id_is_not_special_cased_anywhere_but_the_group(
    client, history, admin_headers, deletable_blob
):
    att_id = await make_attachment(history, owner=ADMIN_ID)

    r = await client.delete(f"/attachments/{att_id}", headers=admin_headers)
    assert r.status_code == 200
