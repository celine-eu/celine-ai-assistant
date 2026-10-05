from __future__ import annotations

import asyncio
import io
import os
import pathlib
import time
import uuid
import zipfile
from dataclasses import dataclass
from typing import Iterator

import fsspec

from .settings import settings


@dataclass(frozen=True)
class StoredFile:
    uri: str
    path: str
    filename: str
    content_type: str | None
    size_bytes: int


class UnsupportedUpload(ValueError):
    """The file is not one of the types an upload may be (see `classify_upload`)."""


# What an upload may be, decided from the bytes. The client's declared type is never
# stored or served: it is whatever the client said.
_MAGIC: tuple[tuple[bytes, int, str], ...] = (
    (b"%PDF", 0, "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"GIF87a", 0, "image/gif"),
    (b"GIF89a", 0, "image/gif"),
)

_OFFICE = {
    ".docx": ("word/", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".xlsx": ("xl/", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".pptx": ("ppt/", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
}

_TEXT = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
}

# Served inline by `/attachments/{id}/raw`; every other allowed type is a download.
INLINE_TYPES = frozenset(
    {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp"}
)

ALLOWED_TYPES = frozenset(
    INLINE_TYPES | {mime for _, mime in _OFFICE.values()} | set(_TEXT.values())
)


def _office_type(data: bytes, ext: str) -> str | None:
    if ext not in _OFFICE or data[:4] != b"PK\x03\x04":
        return None
    prefix, mime = _OFFICE[ext]
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        return None
    if "[Content_Types].xml" in names and any(n.startswith(prefix) for n in names):
        return mime
    return None


def _text_type(data: bytes, ext: str) -> str | None:
    if ext not in _TEXT or b"\x00" in data:
        return None
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return _TEXT[ext]


def classify_upload(data: bytes, filename: str) -> str:
    """The type an upload is stored and served as, from its own bytes.

    PDFs and PNG, JPEG, GIF and WebP images by their magic bytes; Word, Excel and
    PowerPoint (OOXML) by a zip that holds that format's parts, under its extension;
    UTF-8 text without NUL bytes under `.txt`, `.md` or `.csv`. Anything else raises
    `UnsupportedUpload`.
    """
    for magic, offset, mime in _MAGIC:
        if data[offset : offset + len(magic)] == magic:
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    ext = pathlib.PurePosixPath(_sanitize(filename)).suffix.lower()
    mime = _office_type(data, ext) or _text_type(data, ext)
    if mime:
        return mime
    raise UnsupportedUpload(
        "Unsupported file type: upload a PDF, a PNG/JPEG/GIF/WebP image, a "
        ".docx/.xlsx/.pptx document, or .txt/.md/.csv text"
    )


def served_type(stored_type: str | None) -> str:
    """The type a stored attachment is served as.

    Rows written before uploads were classified carry the client's declared type; one
    outside the allow-list is served as opaque bytes.
    """
    mime = (stored_type or "").split(";", 1)[0].strip().lower()
    return mime if mime in ALLOWED_TYPES else "application/octet-stream"


def _fs_and_root():
    uri = settings.uploads_uri
    if uri.startswith("file://"):
        root = uri[len("file://") :]
        fs = fsspec.filesystem("file")
        return fs, root
    if "://" not in uri:
        fs = fsspec.filesystem("file")
        return fs, uri

    scheme = uri.split("://", 1)[0]
    fs = fsspec.filesystem(scheme)
    return fs, uri


def _sanitize(name: str) -> str:
    name = os.path.basename(name).strip().replace(" ", "_")
    return (
        "".join(ch for ch in name if ch.isalnum() or ch in ("_", "-", ".", "+"))[:200]
        or "file"
    )


def _sanitize_owner(owner_user_id: str) -> str:
    """An owner id, made safe to use as a directory name.

    The id is a JWT claim or — with `OAUTH2_TRUST_HEADERS` on — a request header, so it
    is caller-controlled and reaches this function unfiltered. `@`, `.` and `-` are kept
    because an id is very often an email address and rewriting those would move every
    existing user's directory.
    """
    kept = "".join(
        ch for ch in owner_user_id.strip() if ch.isalnum() or ch in ("_", "-", ".", "+", "@")
    )[:200]
    if kept in ("", ".", ".."):
        raise ValueError(f"owner_user_id is not usable as a path: {owner_user_id!r}")
    return kept


def _subdir(scope: str, owner_user_id: str | None, stamp: int) -> str:
    if scope == "system":
        return f"_system/{stamp}"
    if not owner_user_id:
        raise ValueError("owner_user_id required for user scope")
    return f"{_sanitize_owner(owner_user_id)}/{stamp}"


async def store_upload(
    *,
    scope: str,
    owner_user_id: str | None,
    filename: str,
    content_type: str | None,
    data: bytes,
) -> StoredFile:
    fs, root = _fs_and_root()
    safe = _sanitize(filename)
    stamp = int(time.time())
    uid = uuid.uuid4().hex[:10]
    subdir = _subdir(scope, owner_user_id, stamp)
    target = str(pathlib.PurePosixPath(root).joinpath(subdir, f"{uid}_{safe}"))

    def _run() -> StoredFile:
        fs.mkdirs(str(pathlib.PurePosixPath(root).joinpath(subdir)), exist_ok=True)
        with fs.open(target, "wb") as f:
            f.write(data)
        uri = target if "://" in target else f"file://{target}"
        return StoredFile(
            uri=uri,
            path=target,
            filename=safe,
            content_type=content_type,
            size_bytes=len(data),
        )

    return await asyncio.to_thread(_run)


def open_upload_stream(path: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    fs, _ = _fs_and_root()
    with fs.open(path, "rb") as f:
        while True:
            buf = f.read(chunk_size)
            if not buf:
                break
            yield buf


async def delete_upload(path: str) -> None:
    fs, _ = _fs_and_root()

    def _run() -> None:
        if fs.exists(path):
            fs.rm(path)
        return None

    await asyncio.to_thread(_run)
