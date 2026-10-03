"""The registered knowledge sources, and what each last put into each collection."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .db import AsyncSessionLocal, KbSource, KbSourceDocument

SOURCE_KINDS = ("git", "dir")


class KbStore:
    """Same shape as `HistoryStore`: one session per call, a factory for tests."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession] | None = None
    ) -> None:
        self._session = session_factory or AsyncSessionLocal

    async def add_source(
        self,
        *,
        community_id: str,
        kind: str,
        location: str,
        ref: str | None = None,
        subpath: str | None = None,
    ) -> dict[str, Any]:
        if kind not in SOURCE_KINDS:
            raise ValueError(f"unknown source kind {kind!r}")
        async with self._session() as session:
            async with session.begin():
                src = KbSource(
                    id=str(uuid.uuid4()),
                    community_id=community_id,
                    kind=kind,
                    location=location,
                    ref=ref,
                    subpath=subpath or None,
                    created_at=int(time.time()),
                )
                session.add(src)
            return _source_dict(src)

    async def list_sources(self, community_id: str | None = None) -> list[dict[str, Any]]:
        async with self._session() as session:
            stmt = select(KbSource).order_by(KbSource.community_id, KbSource.created_at)
            if community_id:
                stmt = stmt.where(KbSource.community_id == community_id)
            rows = (await session.execute(stmt)).scalars().all()
            return [_source_dict(s) for s in rows]

    async def get_source(self, source_id: str) -> dict[str, Any] | None:
        async with self._session() as session:
            src = await session.get(KbSource, source_id)
            return _source_dict(src) if src else None

    async def remove_source(self, source_id: str) -> dict[str, Any] | None:
        async with self._session() as session:
            async with session.begin():
                src = await session.get(KbSource, source_id)
                if not src:
                    return None
                data = _source_dict(src)
                # Explicit rather than trusting the cascade: SQLite enforces foreign
                # keys only when asked to.
                await session.execute(
                    delete(KbSourceDocument).where(KbSourceDocument.source_id == source_id)
                )
                await session.delete(src)
            return data

    async def mark_synced(self, source_id: str, version: str | None) -> None:
        async with self._session() as session:
            async with session.begin():
                src = await session.get(KbSource, source_id)
                if src:
                    src.last_synced_version = version
                    src.last_synced_at = int(time.time())

    async def document_versions(self, source_id: str, collection: str) -> dict[str, str]:
        async with self._session() as session:
            stmt = select(KbSourceDocument.path, KbSourceDocument.version).where(
                KbSourceDocument.source_id == source_id,
                KbSourceDocument.collection == collection,
            )
            return {path: version for path, version in (await session.execute(stmt)).all()}

    async def set_document_versions(
        self, source_id: str, collection: str, versions: dict[str, str]
    ) -> None:
        async with self._session() as session:
            async with session.begin():
                await session.execute(
                    delete(KbSourceDocument).where(
                        KbSourceDocument.source_id == source_id,
                        KbSourceDocument.collection == collection,
                    )
                )
                session.add_all(
                    KbSourceDocument(
                        source_id=source_id, collection=collection, path=p, version=v
                    )
                    for p, v in versions.items()
                )

    async def forget_collection(self, collection: str) -> None:
        """Drop what was recorded for a collection that no longer exists."""
        async with self._session() as session:
            async with session.begin():
                await session.execute(
                    delete(KbSourceDocument).where(
                        KbSourceDocument.collection == collection
                    )
                )

    async def source_communities(self) -> list[str]:
        async with self._session() as session:
            stmt = select(KbSource.community_id).distinct()
            return sorted((await session.execute(stmt)).scalars().all())


def _source_dict(src: KbSource) -> dict[str, Any]:
    return {
        "id": src.id,
        "community_id": src.community_id,
        "kind": src.kind,
        "location": src.location,
        "ref": src.ref,
        "subpath": src.subpath,
        "last_synced_version": src.last_synced_version,
        "last_synced_at": src.last_synced_at,
        "created_at": src.created_at,
    }
