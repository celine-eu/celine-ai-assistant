from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import time
import uuid
from dataclasses import dataclass
from typing import BinaryIO

import fsspec

from .settings import settings

log = logging.getLogger(__name__)


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
    if scheme == "s3":
        client_kwargs = {}
        if settings.s3_endpoint_url:
            client_kwargs["endpoint_url"] = settings.s3_endpoint_url
        fs = fsspec.filesystem(
            "s3",
            key=settings.s3_access_key_id,
            secret=settings.s3_secret_access_key,
            client_kwargs=client_kwargs,
        )
        return fs, uri
    fs = fsspec.filesystem(scheme)
    return fs, uri


def _sanitize(name: str) -> str:
    name = os.path.basename(name).strip().replace(" ", "_")
    return "".join(ch for ch in name if ch.isalnum() or ch in ("_", "-", ".", "+"))[:200] or "file"


async def store_upload(
    *,
    user_id: str,
    filename: str,
    content_type: str | None,
    data: bytes,
) -> StoredFile:
    fs, root = _fs_and_root()
    safe = _sanitize(filename)
    stamp = int(time.time())
    uid = uuid.uuid4().hex[:10]
    subdir = f"{user_id}/{stamp}"
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
