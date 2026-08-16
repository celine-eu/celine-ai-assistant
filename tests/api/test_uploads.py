"""Upload, extraction and indexing.

Vision and MarkItDown are replaced; the storage layer is real, on a temp directory.
What each test is about is which extraction path a file takes and what ends up in the
vector store afterwards.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from fastapi import HTTPException

from celine.assistant import routes as routes_module
from celine.assistant.settings import settings


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

    async def _upsert(*, text, metadata, doc_id=None):
        state["indexed"].append({"text": text, "metadata": metadata, "doc_id": doc_id})
        return {"inserted": 1}

    monkeypatch.setattr(routes_module, "describe_image", _describe_image)
    monkeypatch.setattr(routes_module, "extract_text", _extract_text)
    monkeypatch.setattr(routes_module, "upsert_documents_from_text", _upsert)
    return state


def png(width: int = 8) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, width), "red").save(buf, format="PNG")
    return buf.getvalue()


async def upload(client, headers, name, data, content_type, path="/upload"):
    return await client.post(
        path, headers=headers, files={"file": (name, data, content_type)}
    )


# --- extraction paths -------------------------------------------------------


# @verifies REQ-0021
async def test_an_image_is_captioned_and_indexed(
    client, history, user_headers, upload_env
):
    r = await upload(client, user_headers, "meter.png", png(), "image/png")

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
    client, user_headers, upload_env
):
    r = await upload(client, user_headers, "bill.pdf", b"%PDF-1.7 ...", "application/pdf")

    assert r.json()["caption"] is None
    (indexed,) = upload_env["indexed"]
    assert indexed["text"].startswith("Document content for bill.pdf:")
    assert indexed["metadata"]["kind"] == "document_content"


async def test_the_sniffed_type_beats_the_declared_one(
    client, user_headers, upload_env
):
    """Browsers routinely declare `application/octet-stream`, and some declare the
    wrong thing outright. The magic bytes decide; the declared type is the fallback.

    @verifies REQ-0021
    """
    await upload(client, user_headers, "mystery.bin", png(), "application/octet-stream")

    assert upload_env["described"] == [None]
    assert upload_env["extracted"] == []


# @verifies REQ-0021
async def test_an_extension_alone_is_enough_to_treat_a_file_as_an_image(
    client, user_headers, upload_env
):
    await upload(client, user_headers, "photo.jpeg", b"not really an image", None)
    assert upload_env["described"] == [None]


async def test_a_file_nothing_can_read_is_stored_not_indexed(
    client, history, user_headers, upload_env
):
    """Failing the upload would lose the file over a parser's opinion. It is kept, and
    reported as `stored` so the caller knows it will not be searchable.

    The `except` around the extraction used to log `extra={"filename": ...}`, which
    `logging` refuses to merge — so the handler meant to contain the failure raised from
    inside itself and this returned 500. See REQ-0034.

    @verifies REQ-0021
    """
    upload_env["extract_raises"] = True

    r = await upload(client, user_headers, "archive.zip", b"PK\x03\x04", "application/zip")

    assert r.status_code == 200
    assert r.json()["status"] == "stored"
    assert len(history.attachments) == 1
    assert upload_env["indexed"] == []


# @verifies REQ-0021
async def test_an_empty_extraction_is_stored_not_indexed(
    client, user_headers, upload_env
):
    upload_env["extract_returns"] = ""

    r = await upload(client, user_headers, "blank.docx", b"PK\x03\x04", None)

    assert r.json()["status"] == "stored"
    assert upload_env["indexed"] == []


# --- what is written to the index -------------------------------------------


async def test_the_owner_is_recorded_in_the_index_metadata(
    client, user_headers, upload_env
):
    """`scope` and `owner_user_id` are what `rag.visibility_filter` and
    `rag.is_visible_to` read back. Writing them and not reading them is what made every
    upload world-readable.

    @verifies REQ-0021 @verifies REQ-0022
    """
    await upload(client, user_headers, "bill.pdf", b"%PDF-1.7", "application/pdf")

    (indexed,) = upload_env["indexed"]
    assert indexed["metadata"]["scope"] == "user"
    assert indexed["metadata"]["owner_user_id"] == "alice"
    assert "hidden" not in indexed["metadata"]


async def test_an_uploaded_document_is_indexed_under_a_derived_id(
    client, history, user_headers, upload_env
):
    """A generated document id would leave the index entry unreachable when the
    attachment is deleted. Deriving it from the attachment id is what makes the deletion
    possible at all.

    @verifies REQ-0021
    """
    body = (
        await upload(client, user_headers, "bill.pdf", b"%PDF-1.7", "application/pdf")
    ).json()

    (indexed,) = upload_env["indexed"]
    assert indexed["doc_id"] == f"attachment:{body['attachment_id']}"


# @verifies REQ-0015
async def test_a_stored_file_lands_under_its_owner(client, user_headers, upload_env):
    body = (await upload(client, user_headers, "my bill.pdf", b"%PDF", "application/pdf")).json()

    assert "/alice/" in body["uri"]
    assert body["filename"] == "my_bill.pdf"


# --- limits -----------------------------------------------------------------


# @verifies REQ-0014
async def test_an_oversized_upload_is_refused(
    client, user_headers, upload_env, monkeypatch
):
    monkeypatch.setattr(settings, "max_upload_mb", 1)

    r = await upload(client, user_headers, "big.bin", b"x" * (1024 * 1024 + 1), None)

    assert r.status_code == 413
    assert "max 1MB" in r.json()["detail"]


async def test_the_limit_never_drops_below_one_megabyte(
    client, user_headers, upload_env, monkeypatch
):
    """`max(1, ...)` means a misconfigured `MAX_UPLOAD_MB=0` still accepts a megabyte
    rather than refusing everything.

    @verifies REQ-0014
    """
    monkeypatch.setattr(settings, "max_upload_mb", 0)

    r = await upload(client, user_headers, "small.bin", b"x" * 1024, None)
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


# --- system uploads ---------------------------------------------------------


# @verifies REQ-0005
async def test_a_system_upload_requires_an_administrator(
    client, user_headers, admin_headers, upload_env
):
    assert (
        await upload(
            client, user_headers, "shared.pdf", b"%PDF", "application/pdf", "/admin/uploads"
        )
    ).status_code == 403

    r = await upload(
        client, admin_headers, "shared.pdf", b"%PDF", "application/pdf", "/admin/uploads"
    )
    assert r.status_code == 200
    assert r.json()["scope"] == "system"


# @verifies REQ-0017
async def test_a_system_upload_has_no_owner(client, admin_headers, upload_env):
    body = (
        await upload(
            client, admin_headers, "shared.pdf", b"%PDF", "application/pdf", "/admin/uploads"
        )
    ).json()

    assert "/_system/" in body["uri"]
    assert upload_env["indexed"][0]["metadata"]["owner_user_id"] is None
