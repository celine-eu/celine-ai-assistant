"""Turning an attachment into knowledge-base text, at upload and again at a rebuild.

The upload route and `celine-assistant kb reindex` go through the same two functions,
so a rebuilt knowledge base holds what the upload path would have written.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .document_processing import detect_mime, extract_text
from .kb_collections import InvalidCommunityId, validate_community_id
from .openai_vision import describe_image
from .rag import attachment_doc_id, upsert_documents_from_text
from .uploads import open_upload_stream

log = logging.getLogger(__name__)


def _is_image(filename: str, content_type: str | None) -> bool:
    if content_type and content_type.startswith("image/"):
        return True
    return filename.lower().endswith(
        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif")
    )


async def extract(
    data: bytes, filename: str, content_type: str | None
) -> tuple[str | None, str | None]:
    """The text to index and, for an image, the caption it is: `(text, caption)`.

    - Images: described with the vision model
    - PDFs / documents: text extracted via the document_processing pipeline
    """
    detected_mime = detect_mime(data)
    effective_mime = (
        detected_mime
        if detected_mime != "application/octet-stream"
        else (content_type or "")
    )

    if _is_image(filename, effective_mime):
        caption = await describe_image(image_bytes=data)
        return caption, caption
    if effective_mime == "application/pdf" or filename.lower().endswith(".pdf"):
        return await extract_text(data, effective_mime, filename), None
    try:
        return await extract_text(data, effective_mime, filename), None
    except Exception:
        # `file`, not `filename`: `filename` is a LogRecord attribute and logging
        # raises rather than overwrite one — from inside this except block.
        log.warning("extract_text_failed", extra={"file": filename})
        return None, None


async def read_blob(path: str) -> bytes:
    return await asyncio.to_thread(lambda: b"".join(open_upload_stream(path)))


async def index_attachment(
    att: dict[str, Any], *, collection: str | None = None
) -> bool:
    """Index one attachment row into its community's knowledge base.

    False when there is nothing to index: no text, or no community to index it into.
    """
    text = att.get("ocr_text")
    community_id = att.get("community_id")
    if not text or not community_id:
        return False
    try:
        validate_community_id(community_id)
    except InvalidCommunityId:
        log.error("kb_unusable_community_id", extra={"community": community_id})
        return False

    caption = att.get("caption")
    filename = att.get("filename") or "file"
    label = (
        f"Image description for {filename}"
        if caption
        else f"Document content for {filename}"
    )
    await upsert_documents_from_text(
        community_id=community_id,
        text=f"{label}:\n{text}",
        metadata={
            "attachment_id": att["id"],
            "source_uri": att.get("uri"),
            "filename": filename,
            "content_type": att.get("content_type"),
            # Read back by `rag.visibility_filter` and `rag.is_visible_to`. Writing
            # them and not reading them is what made every upload world-readable.
            "scope": att["scope"],
            "owner_user_id": att.get("owner_user_id"),
            "kind": "image_caption" if caption else "document_content",
        },
        doc_id=attachment_doc_id(att["id"]),
        collection=collection,
    )
    return True
