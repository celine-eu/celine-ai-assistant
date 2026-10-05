"""Upload, extraction and indexing.

Vision and MarkItDown are replaced; the storage layer is real, on a temp directory.
What each test is about is which extraction path a file takes and what ends up in the
vector store afterwards.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image

from fastapi import HTTPException

from celine.assistant import attachment_index
from celine.assistant import routes as routes_module
from celine.assistant.settings import settings
from tests.conftest import COMMUNITY, OTHER_COMMUNITY


@pytest.fixture
def upload_env(tmp_path, monkeypatch):
    """Real storage, faked extraction, and a record of everything indexed."""
    monkeypatch.setattr(settings, "uploads_uri", f"file://{tmp_path}")

    state: dict = {"indexed": [], "described": [], "extracted": []}

    async def _describe_image(*, image_bytes, filename=None):
        state["described"].append(filename)
        return "A photograph of an electricity meter."

    async def _extract_text(file_bytes, content_type, filename=None):
        state["extracted"].append((content_type, filename))
        if state.get("extract_raises"):
            raise RuntimeError("markitdown cannot read this")
        return state.get("extract_returns", "Total due: 42 EUR")

    async def _upsert(*, community_id, text, metadata, doc_id=None, collection=None):
        state["indexed"].append(
            {
                "community_id": community_id,
                "text": text,
                "metadata": metadata,
                "doc_id": doc_id,
            }
        )
        return {"inserted": 1}

    monkeypatch.setattr(attachment_index, "describe_image", _describe_image)
    monkeypatch.setattr(attachment_index, "extract_text", _extract_text)
    monkeypatch.setattr(attachment_index, "upsert_documents_from_text", _upsert)
    return state


def png(width: int = 8) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, width), "red").save(buf, format="PNG")
    return buf.getvalue()


def docx(parts: tuple[str, ...] = ("word/document.xml",)) -> bytes:
    """An OOXML container: the parts a Word document is recognised by, and no content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        for part in parts:
            zf.writestr(part, "<x/>")
    return buf.getvalue()


async def upload(client, headers, name, data, content_type, path="/upload"):
    return await client.post(
        path, headers=headers, files={"file": (name, data, content_type)}
    )


# --- extraction paths -------------------------------------------------------


# @verifies REQ-0021
async def test_an_image_is_captioned_and_indexed(
    client, history, member_headers, upload_env
):
    r = await upload(client, member_headers, "meter.png", png(), "image/png")

    body = r.json()
    assert r.status_code == 200
    assert body["status"] == "indexed"
    assert body["caption"] == "A photograph of an electricity meter."
    assert body["scope"] == "user"

    stored = await history.get_attachment_any(body["attachment_id"])
    assert stored["caption"] == stored["ocr_text"]

    (indexed,) = upload_env["indexed"]
    assert indexed["text"].startswith("Image description for meter.png:")
    assert indexed["metadata"]["kind"] == "image_caption"


# @verifies REQ-0021
async def test_a_document_is_text_extracted_and_indexed(
    client, member_headers, upload_env
):
    r = await upload(client, member_headers, "bill.pdf", b"%PDF-1.7 ...", "application/pdf")

    assert r.json()["caption"] is None
    (indexed,) = upload_env["indexed"]
    assert indexed["text"].startswith("Document content for bill.pdf:")
    assert indexed["metadata"]["kind"] == "document_content"


async def test_the_sniffed_type_beats_the_declared_one(
    client, member_headers, upload_env
):
    """Browsers routinely declare `application/octet-stream`, and some declare the
    wrong thing outright. The magic bytes decide; the declared type is the fallback.

    @verifies REQ-0021
    """
    await upload(client, member_headers, "mystery.bin", png(), "application/octet-stream")

    assert upload_env["described"] == [None]
    assert upload_env["extracted"] == []


async def test_an_extension_alone_does_not_make_a_file_an_image(
    client, history, member_headers, upload_env
):
    """It used to: a `.jpeg` name sent anything down the image path, and the declared
    type was stored and served as given.

    @verifies REQ-0048
    """
    r = await upload(client, member_headers, "photo.jpeg", b"not really an image", "image/jpeg")

    assert r.status_code == 415
    assert upload_env["described"] == []
    assert history.attachments == {}


async def test_a_file_nothing_can_read_is_stored_not_indexed(
    client, history, member_headers, upload_env
):
    """Failing the upload would lose the file over a parser's opinion. It is kept, and
    reported as `stored` so the caller knows it will not be searchable.

    The `except` around the extraction used to log `extra={"filename": ...}`, which
    `logging` refuses to merge — so the handler meant to contain the failure raised from
    inside itself and this returned 500. See REQ-0034.

    @verifies REQ-0021
    """
    upload_env["extract_raises"] = True

    r = await upload(client, member_headers, "notes.docx", docx(), None)

    assert r.status_code == 200
    assert r.json()["status"] == "stored"
    assert len(history.attachments) == 1
    assert upload_env["indexed"] == []


# @verifies REQ-0021
async def test_an_empty_extraction_is_stored_not_indexed(
    client, member_headers, upload_env
):
    upload_env["extract_returns"] = ""

    r = await upload(client, member_headers, "blank.docx", docx(), None)

    assert r.json()["status"] == "stored"
    assert upload_env["indexed"] == []


# --- what is written to the index -------------------------------------------


async def test_the_owner_is_recorded_in_the_index_metadata(
    client, member_headers, upload_env
):
    """`scope` and `owner_user_id` are what `rag.visibility_filter` and
    `rag.is_visible_to` read back. Writing them and not reading them is what made every
    upload world-readable.

    @verifies REQ-0021 @verifies REQ-0022
    """
    await upload(client, member_headers, "bill.pdf", b"%PDF-1.7", "application/pdf")

    (indexed,) = upload_env["indexed"]
    assert indexed["metadata"]["scope"] == "user"
    assert indexed["metadata"]["owner_user_id"] == "alice"
    assert "hidden" not in indexed["metadata"]


async def test_an_uploaded_document_is_indexed_under_a_derived_id(
    client, history, member_headers, upload_env
):
    """A generated document id would leave the index entry unreachable when the
    attachment is deleted. Deriving it from the attachment id is what makes the deletion
    possible at all.

    @verifies REQ-0021
    """
    body = (
        await upload(client, member_headers, "bill.pdf", b"%PDF-1.7", "application/pdf")
    ).json()

    (indexed,) = upload_env["indexed"]
    assert indexed["doc_id"] == f"attachment:{body['attachment_id']}"


# @verifies REQ-0015
async def test_a_stored_file_lands_under_its_owner(client, member_headers, upload_env):
    body = (await upload(client, member_headers, "my bill.pdf", b"%PDF", "application/pdf")).json()

    assert "/alice/" in body["uri"]
    assert body["filename"] == "my_bill.pdf"


# --- limits -----------------------------------------------------------------


# @verifies REQ-0014
async def test_an_oversized_upload_is_refused(
    client, member_headers, upload_env, monkeypatch
):
    monkeypatch.setattr(settings, "max_upload_mb", 1)

    r = await upload(client, member_headers, "big.bin", b"x" * (1024 * 1024 + 1), None)

    assert r.status_code == 413
    assert "max 1MB" in r.json()["detail"]


async def test_the_limit_never_drops_below_one_megabyte(
    client, member_headers, upload_env, monkeypatch
):
    """`max(1, ...)` means a misconfigured `MAX_UPLOAD_MB=0` still accepts a megabyte
    rather than refusing everything.

    @verifies REQ-0014
    """
    monkeypatch.setattr(settings, "max_upload_mb", 0)

    r = await upload(client, member_headers, "small.txt", b"x" * 1024, None)
    assert r.status_code == 200


async def test_the_body_is_read_in_chunks_and_abandoned_at_the_limit(monkeypatch):
    """Reading the body whole and measuring afterwards would make the limit bound what
    is *stored* rather than what a caller can make this process allocate.

    Checked against the reader directly: through the route, the ASGI transport has
    already buffered the body, so nothing observable is left to measure.

    @verifies REQ-0014
    """
    monkeypatch.setattr(settings, "max_upload_mb", 1)

    class EndlessUpload:
        """A body that never ends — as a caller with a generator would send."""

        def __init__(self) -> None:
            self.served = 0

        async def read(self, size: int = -1) -> bytes:
            assert size > 0, "the whole body must never be asked for at once"
            self.served += size
            return b"x" * size

    body = EndlessUpload()
    with pytest.raises(HTTPException) as exc:
        await routes_module._read_upload_or_413(body)

    assert exc.value.status_code == 413
    # Refused a megabyte in, not after swallowing everything on offer.
    assert body.served <= 2 * 1024 * 1024


# --- the community --------------------------------------------------------


async def test_a_member_s_upload_is_indexed_into_their_community(
    client, history, member_headers, upload_env
):
    """The community comes from the token, never from the request.

    @verifies REQ-0021 @verifies REQ-0040
    """
    body = (
        await upload(client, member_headers, "bill.pdf", b"%PDF-1.7", "application/pdf")
    ).json()

    assert body["community_id"] == COMMUNITY
    assert (await history.get_attachment_any(body["attachment_id"]))["community_id"] == COMMUNITY
    (indexed,) = upload_env["indexed"]
    assert indexed["community_id"] == COMMUNITY


async def test_without_a_community_an_upload_is_stored_not_indexed(
    client, history, user_headers, upload_env
):
    """A caller with no REC can still attach a file to a turn; there is no knowledge
    base to put it in.

    @verifies REQ-0040
    """
    r = await upload(client, user_headers, "bill.pdf", b"%PDF-1.7", "application/pdf")

    assert r.status_code == 200
    assert r.json()["status"] == "stored"
    assert r.json()["community_id"] is None
    assert upload_env["indexed"] == []


async def test_a_member_of_two_communities_is_refused_before_anything_is_stored(
    client, history, tokens, upload_env
):
    """Choosing one would answer from one REC's documents to a member of another.

    @verifies REQ-0040
    """
    headers = tokens.issue(
        "eve",
        organizations={
            COMMUNITY: {"type": ["rec"]},
            OTHER_COMMUNITY: {"type": ["rec"]},
        },
    )

    r = await upload(client, headers, "bill.pdf", b"%PDF-1.7", "application/pdf")

    assert r.status_code == 403
    assert history.attachments == {}


async def test_an_organization_that_is_not_a_rec_is_not_a_community(
    client, tokens, upload_env
):
    """@verifies REQ-0040"""
    headers = tokens.issue("frank", organizations={"example-dso": {"type": ["dso"]}})

    body = (await upload(client, headers, "bill.pdf", b"%PDF", "application/pdf")).json()

    assert body["community_id"] is None


# --- system uploads ---------------------------------------------------------


async def shared(client, headers, community_id=None):
    data = {"community_id": community_id} if community_id else None
    return await client.post(
        "/admin/uploads",
        headers=headers,
        files={"file": ("shared.pdf", b"%PDF", "application/pdf")},
        data=data,
    )


# @verifies REQ-0005
async def test_a_member_cannot_share_with_the_community(
    client, member_headers, upload_env
):
    assert (await shared(client, member_headers)).status_code == 403


# @verifies REQ-0005
async def test_a_manager_shares_with_their_own_community(
    client, manager_headers, upload_env
):
    r = await shared(client, manager_headers)

    assert r.status_code == 200
    assert r.json()["scope"] == "system"
    assert r.json()["community_id"] == COMMUNITY
    assert upload_env["indexed"][0]["community_id"] == COMMUNITY


async def test_a_manager_cannot_share_with_another_community(
    client, manager_headers, upload_env
):
    """A `managers` group inside one REC's organization says nothing about another.

    @verifies REQ-0005
    """
    assert (await shared(client, manager_headers, OTHER_COMMUNITY)).status_code == 403
    assert upload_env["indexed"] == []


async def test_an_admins_group_inside_a_rec_is_not_a_platform_administrator(
    client, tokens, upload_env
):
    """A merged list of every organization's groups (the SDK's retired helper) read
    `admins` inside one REC as an administrator of all of them.

    @verifies REQ-0005
    """
    headers = tokens.issue("grace", community=COMMUNITY, org_groups=("admins",))

    assert (await shared(client, headers)).status_code == 200
    assert (await shared(client, headers, OTHER_COMMUNITY)).status_code == 403


async def test_a_realm_group_in_a_verified_token_grants_nothing(
    client, tokens, upload_env
):
    """Realm groups are gone from the platform. A token that still carries `/admins`
    (and the retired realm role `admin`) is an ordinary caller: no community of its own,
    so it may share with none.

    @verifies REQ-0004 @verifies REQ-0005
    """
    tokens.issue("legacy", groups=("/admins", "admins"), token="legacy-token")
    tokens.claims["legacy-token"]["realm_access"] = {"roles": ["admin"]}
    headers = {"x-auth-request-access-token": "legacy-token"}

    assert (await shared(client, headers, COMMUNITY)).status_code == 403
    assert (await shared(client, headers, OTHER_COMMUNITY)).status_code == 403
    assert upload_env["indexed"] == []
    body = (await client.get("/user", headers=headers)).json()
    assert body["is_platform_admin"] is False
    assert body["is_admin"] is False


async def test_a_header_claiming_the_role_is_not_a_platform_administrator(
    client, upload_env
):
    """With header trust on (dev only), the headers name a caller and nothing more.

    @verifies REQ-0003 @verifies REQ-0004
    """
    headers = {
        "x-auth-request-user": "mallory",
        "x-auth-request-groups": "admins,platform-admin,role:platform-admin",
    }

    assert (await shared(client, headers, COMMUNITY)).status_code == 403
    assert upload_env["indexed"] == []


# @verifies REQ-0005
async def test_a_platform_administrator_names_the_community(
    client, admin_headers, upload_env
):
    assert (await shared(client, admin_headers)).status_code == 400

    r = await shared(client, admin_headers, OTHER_COMMUNITY)
    assert r.status_code == 200
    assert r.json()["community_id"] == OTHER_COMMUNITY


# @verifies REQ-0005
async def test_a_community_id_that_cannot_name_a_knowledge_base_is_refused(
    client, admin_headers, upload_env
):
    assert (await shared(client, admin_headers, "Not A Name")).status_code == 400


# @verifies REQ-0017
async def test_a_system_upload_has_no_owner(client, manager_headers, upload_env):
    body = (await shared(client, manager_headers)).json()

    assert "/_system/" in body["uri"]
    assert upload_env["indexed"][0]["metadata"]["owner_user_id"] is None


# --- what an upload may be ----------------------------------------------------


@pytest.mark.parametrize(
    ("name", "data", "declared"),
    [
        ("page.html", b"<html><script>alert(1)</script></html>", "text/html"),
        ("image.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
        ("tool.exe", b"MZ\x90\x00", "application/octet-stream"),
    ],
)
async def test_a_type_outside_the_allow_list_is_refused_before_it_is_stored(
    client, history, member_headers, upload_env, name, data, declared
):
    """@verifies REQ-0048"""
    r = await upload(client, member_headers, name, data, declared)

    assert r.status_code == 415
    assert history.attachments == {}
    assert upload_env["indexed"] == []


async def test_the_stored_type_is_the_sniffed_one_not_the_declared_one(
    client, history, member_headers, upload_env
):
    """@verifies REQ-0048"""
    r = await upload(client, member_headers, "meter.png", png(), "text/html")

    assert r.status_code == 200
    assert r.json()["content_type"] == "image/png"
    (att,) = history.attachments.values()
    assert att["content_type"] == "image/png"


async def test_a_system_upload_is_held_to_the_same_list(
    client, history, manager_headers, upload_env
):
    """@verifies REQ-0048"""
    r = await client.post(
        "/admin/uploads",
        headers=manager_headers,
        files={"file": ("page.html", b"<html></html>", "text/html")},
    )

    assert r.status_code == 415
    assert history.attachments == {}
