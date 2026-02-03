from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import pathlib
import tempfile
from dataclasses import dataclass
from typing import Any

import fsspec

from .settings import settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ObjectInfo:
    uri: str
    path: str
    etag: str | None
    mtime: str | None
    size: int | None


def _fs_and_root():
    uri = settings.docs_uri
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


async def list_objects() -> list[ObjectInfo]:
    fs, root = _fs_and_root()

    def _run():
        paths = fs.find(root)
        out: list[ObjectInfo] = []
        for p in paths:
            try:
                info = fs.info(p) or {}
            except Exception:
                info = {}
            size = info.get("size")
            mtime = info.get("LastModified") or info.get("mtime") or info.get("last_modified")
            etag = info.get("ETag") or info.get("etag")
            uri = p if "://" in p else f"file://{p}"
            out.append(ObjectInfo(uri=uri, path=p, etag=str(etag) if etag else None, mtime=str(mtime) if mtime else None, size=int(size) if size is not None else None))
        return out

    return await asyncio.to_thread(_run)


async def download_to_temp(path: str) -> str:
    fs, _ = _fs_and_root()

    def _run():
        fd, tmp = tempfile.mkstemp(prefix="doc_", suffix=pathlib.Path(path).suffix)
        os.close(fd)
        with fs.open(path, "rb") as fsrc, open(tmp, "wb") as fdst:
            while True:
                buf = fsrc.read(1024 * 1024)
                if not buf:
                    break
                fdst.write(buf)
        return tmp

    return await asyncio.to_thread(_run)
