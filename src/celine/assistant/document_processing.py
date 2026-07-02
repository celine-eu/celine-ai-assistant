"""Document processing pipeline for PDFs, images, and office documents.

Ported from onboarding repo's openai_extractor patterns. Provides unified
text extraction with fallbacks: MarkItDown for text-based PDFs and office
formats, PyMuPDF page-rendering + vision for scanned documents.
"""

from __future__ import annotations

import asyncio
import io
import logging
import tempfile
from pathlib import Path

import pymupdf
from markitdown import MarkItDown
from PIL import Image

from .openai_vision import describe_image

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_DIMENSION = 1600
JPEG_QUALITY = 75
PDF_DPI = 200
MIN_TEXT_LENGTH = 100


# ---------------------------------------------------------------------------
# MIME detection via magic bytes
# ---------------------------------------------------------------------------


def detect_mime(data: bytes) -> str:
    """Detect MIME type from leading magic bytes."""
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"


# ---------------------------------------------------------------------------
# Image compression
# ---------------------------------------------------------------------------


def compress_image(image_bytes: bytes) -> tuple[bytes, str]:
    """Compress/resize an image to max 1600px, JPEG quality 75."""
    img = Image.open(io.BytesIO(image_bytes))
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_DIMENSION:
        ratio = MAX_DIMENSION / max(w, h)
        img = img.resize(
            (int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS
        )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue(), "image/jpeg"


# ---------------------------------------------------------------------------
# PDF text extraction via MarkItDown
# ---------------------------------------------------------------------------


def pdf_to_text(pdf_bytes: bytes) -> str:
    """Extract text from a PDF using MarkItDown."""
    md = MarkItDown()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    try:
        result = md.convert(tmp_path)
        return result.text_content
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# PDF page rendering via PyMuPDF (fallback for scanned PDFs)
# ---------------------------------------------------------------------------


def pdf_to_images(pdf_bytes: bytes) -> list[tuple[bytes, str]]:
    """Render each PDF page as a compressed JPEG image."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    images: list[tuple[bytes, str]] = []
    for page in doc:
        pix = page.get_pixmap(dpi=PDF_DPI)
        img_bytes = pix.tobytes("jpeg")
        compressed, cmime = compress_image(img_bytes)
        images.append((compressed, cmime))
    doc.close()
    return images


# ---------------------------------------------------------------------------
# Generic file-to-text via MarkItDown (docx, xlsx, pptx, etc.)
# ---------------------------------------------------------------------------


def _markitdown_convert(file_bytes: bytes, filename: str | None) -> str:
    """Run MarkItDown on an arbitrary file written to a temp path."""
    suffix = ""
    if filename:
        suffix = Path(filename).suffix or ""
    md = MarkItDown()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        result = md.convert(tmp_path)
        return result.text_content
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Unified async extraction entry-point
# ---------------------------------------------------------------------------


async def extract_text(
    file_bytes: bytes,
    content_type: str | None,
    filename: str | None = None,
) -> str:
    """Extract text from a file using the best available strategy.

    - PDFs: try MarkItDown text extraction first; fall back to rendering
      pages as images and describing them via OpenAI vision.
    - Images: use ``describe_image`` directly.
    - Other types (docx, xlsx, pptx, ...): delegate to MarkItDown.

    Blocking operations are wrapped in ``asyncio.to_thread``.
    """
    detected = detect_mime(file_bytes)
    effective_mime = (
        detected if detected != "application/octet-stream" else (content_type or "")
    )

    # --- PDF path ---
    if effective_mime == "application/pdf" or (
        filename and filename.lower().endswith(".pdf")
    ):
        text = await asyncio.to_thread(pdf_to_text, file_bytes)
        if len(text.strip()) >= MIN_TEXT_LENGTH:
            return text

        # Scanned PDF fallback: render pages and describe via vision
        log.info(
            "pdf_text_too_short_falling_back_to_vision",
            extra={"filename": filename, "text_len": len(text.strip())},
        )
        page_images = await asyncio.to_thread(pdf_to_images, file_bytes)
        descriptions: list[str] = []
        for idx, (img_data, _mime) in enumerate(page_images):
            desc = await describe_image(
                image_bytes=img_data,
                filename=f"{filename or 'page'}_{idx + 1}.jpg",
            )
            descriptions.append(f"[Page {idx + 1}]\n{desc}")
        return "\n\n".join(descriptions)

    # --- Image path ---
    if effective_mime.startswith("image/"):
        return await describe_image(image_bytes=file_bytes, filename=filename)

    # --- Generic office / other formats via MarkItDown ---
    return await asyncio.to_thread(_markitdown_convert, file_bytes, filename)
