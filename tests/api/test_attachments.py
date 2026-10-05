"""Who may read, list and delete an attachment.

Two scopes exist — `user` and `system` — and the rules differ per verb, which is why
this is a matrix rather than a helper. A `system` attachment belongs to one community:
its members read it, its managers delete it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from celine.assistant import routes as routes_module
from tests.conftest import ADMIN_ID, COMMUNITY, NEIGHBOUR_ID, OTHER_COMMUNITY, USER_ID


async def make_attachment(history, scope="user", owner=USER_ID, **overrides) -> str:
    payload = {
        "scope": scope,
        "owner_user_id": owner if scope == "user" else None,
        "community_id": COMMUNITY,
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
async def test_a_listing_shows_own_and_system_attachments(client, history, member_headers):
    mine = await make_attachment(history)
    shared = await make_attachment(history, scope="system")
    await make_attachment(history, owner=NEIGHBOUR_ID)

    await make_attachment(history, scope="system", community_id=OTHER_COMMUNITY)

    body = (await client.get("/attachments", headers=member_headers)).json()

    assert {a["id"] for a in body["items"]} == {mine, shared}


# @verifies REQ-0019
async def test_without_a_community_a_listing_shows_only_own_attachments(
    client, history, user_headers
):
    mine = await make_attachment(history, community_id=None)
    await make_attachment(history, scope="system")

    body = (await client.get("/attachments", headers=user_headers)).json()

    assert {a["id"] for a in body["items"]} == {mine}


# --- reading ----------------------------------------------------------------


# @verifies REQ-0016
async def test_the_owner_can_read_their_attachment(
    client, history, member_headers, readable_blob
):
    att_id = await make_attachment(history)

    r = await client.get(f"/attachments/{att_id}/raw", headers=member_headers)

    assert r.status_code == 200
    assert r.content == b"PDF-BYTES"
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.headers["content-disposition"] == 'inline; filename="bill.pdf"'


# @verifies REQ-0016
async def test_another_user_cannot_read_it(client, history, neighbour_headers):
    att_id = await make_attachment(history)

    r = await client.get(f"/attachments/{att_id}/raw", headers=neighbour_headers)
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
async def test_a_system_attachment_is_readable_by_any_member_of_its_community(
    client, history, neighbour_headers, readable_blob
):
    att_id = await make_attachment(history, scope="system")

    r = await client.get(f"/attachments/{att_id}/raw", headers=neighbour_headers)
    assert r.status_code == 200


# @verifies REQ-0017
async def test_another_community_s_system_attachment_is_not_readable(
    client, history, outsider_headers, user_headers, readable_blob
):
    att_id = await make_attachment(history, scope="system")

    for headers in (outsider_headers, user_headers):
        r = await client.get(f"/attachments/{att_id}/raw", headers=headers)
        assert r.status_code == 403


# @verifies REQ-0020
async def test_reading_an_unknown_attachment_is_not_found(client, member_headers):
    r = await client.get("/attachments/nope/raw", headers=member_headers)
    assert r.status_code == 404


async def test_an_unrecognised_scope_is_an_internal_error(
    client, history, member_headers
):
    """Neither `user` nor `system` means the row is not one this code wrote. It refuses
    rather than guessing — a 500 here is a data-integrity signal, not a bug.

    @verifies REQ-0016
    """
    att_id = await make_attachment(history, scope="team")

    r = await client.get(f"/attachments/{att_id}/raw", headers=member_headers)
    assert r.status_code == 500


# --- deleting ---------------------------------------------------------------


@pytest.fixture
def deletable_blob(monkeypatch):
    """Records the blob paths deleted, and the document ids deleted from the index."""
    deleted: list[str] = []
    unindexed: list[str] = []

    async def _delete(path: str) -> None:
        deleted.append(path)

    async def _delete_document(doc_id: str, *, community_id: str) -> None:
        unindexed.append((community_id, doc_id))

    monkeypatch.setattr(routes_module, "delete_upload", _delete)
    monkeypatch.setattr(routes_module, "delete_document", _delete_document)
    return SimpleNamespace(blobs=deleted, documents=unindexed)


# @verifies REQ-0016
async def test_the_owner_can_delete_their_attachment(
    client, history, member_headers, deletable_blob
):
    att_id = await make_attachment(history)

    r = await client.delete(f"/attachments/{att_id}", headers=member_headers)

    assert r.status_code == 200
    assert await history.get_attachment_any(att_id) is None
    assert deletable_blob.blobs == ["/tmp/bill.pdf"]


# @verifies REQ-0016
async def test_another_user_cannot_delete_it(
    client, history, neighbour_headers, deletable_blob
):
    att_id = await make_attachment(history)

    r = await client.delete(f"/attachments/{att_id}", headers=neighbour_headers)

    assert r.status_code == 403
    assert await history.get_attachment_any(att_id) is not None


# @verifies REQ-0018
async def test_only_a_manager_or_administrator_may_delete_a_system_attachment(
    client, history, member_headers, manager_headers, admin_headers, deletable_blob
):
    first = await make_attachment(history, scope="system")
    second = await make_attachment(history, scope="system")

    assert (
        await client.delete(f"/attachments/{first}", headers=member_headers)
    ).status_code == 403
    assert (
        await client.delete(f"/attachments/{first}", headers=manager_headers)
    ).status_code == 200
    assert (
        await client.delete(f"/attachments/{second}", headers=admin_headers)
    ).status_code == 200


# @verifies REQ-0018
async def test_a_manager_cannot_delete_another_community_s_system_attachment(
    client, history, manager_headers, deletable_blob
):
    att_id = await make_attachment(history, scope="system", community_id=OTHER_COMMUNITY)

    r = await client.delete(f"/attachments/{att_id}", headers=manager_headers)

    assert r.status_code == 403
    assert await history.get_attachment_any(att_id) is not None


async def test_an_attachment_with_no_community_has_nothing_to_unindex(
    client, history, user_headers, deletable_blob
):
    """Rows from before knowledge bases were per community, and uploads by a caller
    with no REC, were never indexed into one.

    @verifies REQ-0021
    """
    att_id = await make_attachment(history, community_id=None)

    r = await client.delete(f"/attachments/{att_id}", headers=user_headers)

    assert r.status_code == 200
    assert deletable_blob.documents == []


async def test_the_row_is_removed_even_when_the_blob_will_not_delete(
    client, history, member_headers, monkeypatch
):
    """Storage may be gone, read-only or simply wrong; leaving an unreachable row
    behind would be worse than an orphaned blob.

    @verifies REQ-0016
    """

    async def _explode(path: str) -> None:
        raise OSError("read-only filesystem")

    async def _delete_document(doc_id: str, *, community_id: str) -> None:
        return None

    monkeypatch.setattr(routes_module, "delete_upload", _explode)
    monkeypatch.setattr(routes_module, "delete_document", _delete_document)
    att_id = await make_attachment(history)

    r = await client.delete(f"/attachments/{att_id}", headers=member_headers)

    assert r.status_code == 200
    assert await history.get_attachment_any(att_id) is None


# @verifies REQ-0020
async def test_deleting_an_unknown_attachment_is_not_found(client, member_headers):
    r = await client.delete("/attachments/nope", headers=member_headers)
    assert r.status_code == 404


async def test_deleting_an_attachment_also_removes_it_from_the_index(
    client, history, member_headers, deletable_blob
):
    """An attachment is three things: a row, a blob, and a document in the vector store.
    Leaving the last one behind meant deleted content stayed retrievable and quotable
    for as long as the collection did — which is not a deletion.

    @verifies REQ-0021 @verifies REQ-0022
    """
    att_id = await make_attachment(history)

    await client.delete(f"/attachments/{att_id}", headers=member_headers)

    assert deletable_blob.documents == [(COMMUNITY, f"attachment:{att_id}")]


async def test_the_row_is_removed_even_when_the_index_will_not_delete(
    client, history, member_headers, monkeypatch
):
    """Qdrant being unreachable must not strand the attachment as undeletable. The
    failure is logged; what is owed afterwards is a reindex, not a retry the caller has
    to drive.

    @verifies REQ-0021
    """

    async def _explode(doc_id: str, *, community_id: str) -> None:
        raise RuntimeError("qdrant unreachable")

    async def _delete_blob(path: str) -> None:
        return None

    monkeypatch.setattr(routes_module, "delete_document", _explode)
    monkeypatch.setattr(routes_module, "delete_upload", _delete_blob)
    att_id = await make_attachment(history)

    r = await client.delete(f"/attachments/{att_id}", headers=member_headers)

    assert r.status_code == 200
    assert await history.get_attachment_any(att_id) is None


# @verifies REQ-0018
async def test_an_admin_id_is_not_special_cased_anywhere_but_the_group(
    client, history, admin_headers, deletable_blob
):
    att_id = await make_attachment(history, owner=ADMIN_ID)

    r = await client.delete(f"/attachments/{att_id}", headers=admin_headers)
    assert r.status_code == 200


# --- how a file is served -----------------------------------------------------


async def test_a_pdf_is_inline_and_never_sniffed(
    client, history, member_headers, readable_blob
):
    """@verifies REQ-0049"""
    att_id = await make_attachment(history)

    r = await client.get(f"/attachments/{att_id}/raw", headers=member_headers)

    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "private, no-store"


async def test_an_image_is_inline_in_a_sandbox(
    client, history, member_headers, readable_blob
):
    """@verifies REQ-0049"""
    att_id = await make_attachment(
        history, filename="meter.png", content_type="image/png"
    )

    r = await client.get(f"/attachments/{att_id}/raw", headers=member_headers)

    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"] == 'inline; filename="meter.png"'
    assert r.headers["x-content-type-options"] == "nosniff"
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "sandbox" in csp


@pytest.mark.parametrize(
    ("stored_type", "served"),
    [
        # Rows written before uploads were typed: the client's declared type.
        ("text/html", "application/octet-stream"),
        ("image/svg+xml", "application/octet-stream"),
        ("application/javascript", "application/octet-stream"),
        (None, "application/octet-stream"),
        # Allowed, but not a format a browser should render from this origin.
        ("text/plain", "text/plain"),
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ],
)
async def test_anything_but_an_image_or_pdf_is_a_download(
    client, history, member_headers, readable_blob, stored_type, served
):
    """@verifies REQ-0049"""
    att_id = await make_attachment(
        history, filename="page.html", content_type=stored_type
    )

    r = await client.get(f"/attachments/{att_id}/raw", headers=member_headers)

    assert r.status_code == 200
    assert r.headers["content-type"].split(";")[0] == served
    assert r.headers["content-disposition"] == 'attachment; filename="page.html"'
    assert r.headers["x-content-type-options"] == "nosniff"
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "sandbox" in csp


async def test_a_non_ascii_name_is_carried_encoded(
    client, history, member_headers, readable_blob
):
    """The sanitiser keeps letters of any script (REQ-0015); a raw header cannot.

    @verifies REQ-0049
    """
    att_id = await make_attachment(history, filename="日本語.pdf")

    r = await client.get(f"/attachments/{att_id}/raw", headers=member_headers)

    assert r.status_code == 200
    assert r.headers["content-disposition"] == (
        "inline; filename=\".pdf\"; filename*=UTF-8''%E6%97%A5%E6%9C%AC%E8%AA%9E.pdf"
    )
