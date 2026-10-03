"""Operating the knowledge bases: what `celine-assistant kb` does.

A rebuild never copies vectors. It builds a new generation from the sources and the
attachment rows, checks it holds every document it should, and only then moves the
alias — so a failed rebuild leaves the live knowledge base as it was.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from . import kb_collections, kb_sources, rag
from .attachment_index import extract, index_attachment, read_blob
from .history import HistoryStore
from .kb_store import KbStore
from .settings import settings

log = logging.getLogger(__name__)


class RebuildError(RuntimeError):
    pass


async def communities(history: HistoryStore, kb_store: KbStore) -> list[str]:
    """Every community with sources, attachments or a knowledge base."""
    known = set(await history.attachment_communities())
    known |= set(await kb_store.source_communities())
    aliases = await asyncio.to_thread(kb_collections.aliases, rag.qdrant())
    for alias in aliases:
        parsed = kb_collections.parse_name(alias)
        if parsed:
            known.add(parsed.community_id)
    return sorted(known)


async def status(history: HistoryStore, kb_store: KbStore) -> dict[str, Any]:
    client = rag.qdrant()
    fp = kb_collections.fingerprint()
    aliases = await asyncio.to_thread(kb_collections.aliases, client)
    generations = await asyncio.to_thread(kb_collections.generations, client)
    names = {c.name for c in (await asyncio.to_thread(client.get_collections)).collections}

    rows = []
    for community_id in await communities(history, kb_store):
        alias = kb_collections.alias_name(community_id, fp)
        collection = aliases.get(alias)
        others = [
            {"alias": a, "collection": c}
            for a, c in aliases.items()
            if a != alias
            and (parsed := kb_collections.parse_name(a))
            and parsed.community_id == community_id
        ]
        rows.append(
            {
                "community_id": community_id,
                "alias": alias,
                "collection": collection,
                "points": (
                    await asyncio.to_thread(rag.count_points, collection)
                    if collection
                    else None
                ),
                "other_models": others,
                "sources": await kb_store.list_sources(community_id),
                "attachments": len(
                    await history.list_attachments_for_community(community_id)
                ),
            }
        )

    return {
        "model": settings.llm_embed_model,
        "dimensions": kb_collections.embedding_dimensions(),
        "fingerprint": fp,
        "communities": rows,
        "unaliased_generations": [g for g in generations if g not in aliases.values()],
        # What this service wrote before knowledge bases were per community.
        "legacy_collection": settings.qdrant_collection
        if settings.qdrant_collection in names
        else None,
        "attachments_without_community": await history.count_attachments_without_community(),
    }


async def _catch_up(
    community_id: str, collection: str, history: HistoryStore
) -> dict[str, int]:
    """Make `collection` match the attachment rows as they are now.

    Uploads and deletes that happened while it was being built went to the previous
    generation. Upserts replace by document id, so re-applying one is harmless.
    """
    rows = {
        a["id"]: a
        for a in await history.list_attachments_for_community(community_id)
        if a.get("ocr_text")
    }
    indexed = await asyncio.to_thread(rag.indexed_values, collection, "attachment_id")
    added = removed = 0
    for att_id in rows.keys() - indexed:
        if await index_attachment(rows[att_id], collection=collection):
            added += 1
    for att_id in indexed - rows.keys():
        await rag.delete_document(
            rag.attachment_doc_id(att_id), community_id=community_id, collection=collection
        )
        removed += 1
    return {"added": added, "removed": removed}


async def reindex(
    community_id: str,
    *,
    history: HistoryStore,
    kb_store: KbStore,
    re_extract: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    kb_collections.validate_community_id(community_id)
    sources = await kb_store.list_sources(community_id)
    attachments = await history.list_attachments_for_community(community_id)
    alias = kb_collections.alias_name(community_id)

    if dry_run:
        return {
            "community_id": community_id,
            "alias": alias,
            "sources": [s["id"] for s in sources],
            "attachments": len(attachments),
            "re_extract": re_extract,
            "dry_run": True,
        }

    client = rag.qdrant()
    collection = await asyncio.to_thread(
        kb_collections.create_generation, client, community_id
    )
    expected: set[str] = set()
    try:
        source_results = []
        for source in sources:
            root, version = await asyncio.to_thread(kb_sources.prepare, source)
            result = await kb_sources.ingest(
                source, root, kb_store=kb_store, collection=collection, full=True
            )
            await kb_store.mark_synced(source["id"], version)
            expected |= {
                kb_sources.source_doc_id(source["id"], d.rel_path)
                for d in kb_sources.read_documents(root)
            }
            source_results.append({"source_id": source["id"], "version": version, **result})

        extracted = 0
        for att in attachments:
            if re_extract:
                data = await read_blob(att["path"])
                text, caption = await extract(data, att["filename"], att.get("content_type"))
                await history.update_attachment_text(att["id"], ocr_text=text, caption=caption)
                att = {**att, "ocr_text": text, "caption": caption}
                extracted += 1
            if await index_attachment(att, collection=collection):
                expected.add(rag.attachment_doc_id(att["id"]))

        indexed = await asyncio.to_thread(rag.indexed_values, collection, "doc_id")
        if missing := expected - indexed:
            raise RebuildError(
                f"{len(missing)} of {len(expected)} documents did not reach {collection}"
            )
    except BaseException:
        log.exception("kb_reindex_failed", extra={"collection": collection})
        await asyncio.to_thread(client.delete_collection, collection)
        await kb_store.forget_collection(collection)
        raise

    previous = await asyncio.to_thread(kb_collections.point_alias, client, alias, collection)
    caught_up = await _catch_up(community_id, collection, history)
    return {
        "community_id": community_id,
        "alias": alias,
        "collection": collection,
        "previous": previous,
        "sources": source_results,
        "attachments": len(attachments),
        "re_extracted": extracted,
        "documents": len(expected),
        "points": await asyncio.to_thread(rag.count_points, collection),
        "caught_up": caught_up,
    }


async def prune(
    *, kb_store: KbStore, keep: int = 0, legacy: bool = False, dry_run: bool = False
) -> list[str]:
    """Delete generations no alias points to, keeping the newest `keep` of each
    community and model. `legacy` also deletes the pre-community collection."""
    client = rag.qdrant()
    aliased = set((await asyncio.to_thread(kb_collections.aliases, client)).values())
    groups: dict[str, list[str]] = {}
    for name in await asyncio.to_thread(kb_collections.generations, client):
        if name in aliased:
            continue
        parsed = kb_collections.parse_name(name)
        if parsed:
            groups.setdefault(parsed.alias, []).append(name)

    doomed: list[str] = []
    for names in groups.values():
        names.sort(reverse=True)  # the timestamp sorts
        doomed.extend(names[keep:])

    if legacy:
        existing = {c.name for c in (await asyncio.to_thread(client.get_collections)).collections}
        if settings.qdrant_collection in existing:
            doomed.append(settings.qdrant_collection)

    if not dry_run:
        for name in doomed:
            await asyncio.to_thread(client.delete_collection, name)
            await kb_store.forget_collection(name)
            log.info("kb_collection_deleted", extra={"collection": name})
    return sorted(doomed)


async def migrate_legacy(
    community_id: str,
    *,
    history: HistoryStore,
    kb_store: KbStore,
    git_url: str | None = None,
    ref: str | None = None,
    subpath: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Move everything from before knowledge bases were per community into one.

    Attachments with no community are given this one. The training-materials
    repository — named here, or by a leftover `TRAINING_MATERIALS_REPO_URL` — becomes
    this community's git source. Then the community is rebuilt.
    """
    kb_collections.validate_community_id(community_id)
    git_url = git_url or settings.removed_training_materials_repo_url or None
    ref = ref or settings.removed_training_materials_ref or None
    unassigned = await history.count_attachments_without_community()
    existing = await kb_store.list_sources(community_id)
    register = bool(git_url) and not any(
        s["kind"] == "git" and s["location"] == git_url for s in existing
    )

    if dry_run:
        return {
            "community_id": community_id,
            "attachments_to_assign": unassigned,
            "source_to_register": git_url if register else None,
            "dry_run": True,
        }

    assigned = await history.assign_community_to_unassigned(community_id)
    source = None
    if register:
        source = await kb_store.add_source(
            community_id=community_id, kind="git", location=git_url, ref=ref, subpath=subpath
        )
    rebuilt = await reindex(community_id, history=history, kb_store=kb_store)
    return {
        "community_id": community_id,
        "attachments_assigned": assigned,
        "source_registered": source,
        "reindex": rebuilt,
    }
