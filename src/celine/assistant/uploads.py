from __future__ import annotations

import asyncio
import os
import pathlib
import time
import uuid
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


def _subdir(scope: str, owner_user_id: str | None, stamp: int) -> str:
    if scope == "system":
        return f"_system/{stamp}"
    if not owner_user_id:
        raise ValueError("owner_user_id required for user scope")
    return f"{owner_user_id}/{stamp}"


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
