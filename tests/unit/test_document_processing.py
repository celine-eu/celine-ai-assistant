"""MIME sniffing and image normalisation.

`extract_text` itself is not covered here: every branch of it ends in MarkItDown, a
PDF renderer or the vision model. What is ours is the dispatch, and the dispatch is
decided by `detect_mime`.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from celine.assistant.document_processing import (
    MAX_DIMENSION,
    compress_image,
    detect_mime,
)


def png_bytes(width: int = 10, height: int = 10) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"%PDF-1.7\nrest", "application/pdf"),
        (b"\xff\xd8\xff\xe0 jfif", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\nrest", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"GIF87a...", "image/gif"),
        (b"GIF89a...", "image/gif"),
    ],
)
# @verifies REQ-0021
def test_known_magic_bytes_are_recognised(data, expected):
    assert detect_mime(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"PK\x03\x04",  # a docx or xlsx — zip-based formats are not sniffed
        b"plain text",
        b"RIFF\x00\x00\x00\x00WAVE",  # a RIFF container that is not WebP
    ],
)
def test_anything_else_is_reported_as_an_opaque_stream(data):
    """The uploader's declared content type is what decides the path for these.

    @verifies REQ-0021
    """
    assert detect_mime(data) == "application/octet-stream"


# @verifies REQ-0021
def test_a_large_image_is_scaled_to_fit_and_re_encoded_as_jpeg():
    out, mime = compress_image(png_bytes(4000, 2000))

    assert mime == "image/jpeg"
    scaled = Image.open(io.BytesIO(out))
    assert max(scaled.size) == MAX_DIMENSION
    assert scaled.size == (MAX_DIMENSION, MAX_DIMENSION // 2)


# @verifies REQ-0021
def test_a_small_image_keeps_its_dimensions():
    out, _ = compress_image(png_bytes(64, 32))
    assert Image.open(io.BytesIO(out)).size == (64, 32)


def test_transparency_is_flattened_rather_than_rejected():
    """JPEG has no alpha channel, so the convert to RGB is what stops a PNG with
    transparency from raising on save.

    @verifies REQ-0021
    """
    buf = io.BytesIO()
    Image.new("RGBA", (10, 10), (255, 0, 0, 0)).save(buf, format="PNG")

    out, mime = compress_image(buf.getvalue())
    assert mime == "image/jpeg"
    assert Image.open(io.BytesIO(out)).mode == "RGB"


def blank_pdf() -> bytes:
    """A PDF with no extractable text — what a scan looks like to MarkItDown."""
    import pymupdf

    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


async def test_a_scanned_pdf_falls_back_to_describing_its_pages(monkeypatch):
    """A PDF whose extracted text comes back under `MIN_TEXT_LENGTH` is a scan: there is
    nothing to read, so each page is rendered and described instead.

    The log line announcing the fallback used to pass `extra={"filename": ...}`, which
    `logging` refuses to merge — so this path raised before rendering a single page, and
    every scanned PDF returned 500. See REQ-0034.

    @verifies REQ-0021
    """
    from celine.assistant import document_processing as dp

    rendered: list[bytes] = []
    monkeypatch.setattr(
        dp, "pdf_to_images", lambda data: rendered.append(data) or [(b"jpeg", "image/jpeg")]
    )

    async def _describe(*, image_bytes, filename=None):
        return f"a page called {filename}"

    monkeypatch.setattr(dp, "describe_image", _describe)

    text = await dp.extract_text(blank_pdf(), "application/pdf", "scan.pdf")

    assert rendered
    assert text == "[Page 1]\na page called scan.pdf_1.jpg"
