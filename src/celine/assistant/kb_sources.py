"""Registered sources — a git repository or a directory — feeding a community's knowledge.

What used to be the one training-materials repository is now one source among any,
each bound to a single community. Markdown is read, as it was; front matter is
stripped and the first heading is the title.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import rag
from .kb_store import KbStore
from .settings import Settings, settings

log = logging.getLogger(__name__)
_sync_lock = asyncio.Lock()


# Ingestion settings that knowledge sources replaced. Reported, not refused: the
# service runs without them, and a deployment's chart may still set them.
_REMOVED_INGESTION = {
    "removed_training_materials_path": "TRAINING_MATERIALS_PATH",
    "removed_training_materials_repo_url": "TRAINING_MATERIALS_REPO_URL",
    "removed_training_materials_ref": "TRAINING_MATERIALS_REF",
    "removed_training_materials_sync_on_start": "TRAINING_MATERIALS_SYNC_ON_START",
    "removed_manifest_path": "MANIFEST_PATH",
    "removed_ingest_enable": "INGEST_ENABLE",
    "removed_ingest_force_reload_on_start": "INGEST_FORCE_RELOAD_ON_START",
    "removed_docs_poll_interval_seconds": "DOCS_POLL_INTERVAL_SECONDS",
}


def removed_ingestion_settings(cfg: Settings) -> list[str]:
    return [name for field, name in _REMOVED_INGESTION.items() if getattr(cfg, field)]


class SourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceDocument:
    rel_path: str
    title: str
    text: str
    location: str

    @property
    def version(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def source_doc_id(source_id: str, rel_path: str) -> str:
    return f"source:{source_id}:{rel_path}"


def checkout_path(source: dict[str, Any]) -> Path:
    if source["kind"] == "git":
        return Path(settings.kb_sources_dir).resolve() / source["id"]
    return Path(source["location"]).resolve()


def content_root(source: dict[str, Any]) -> Path:
    base = checkout_path(source)
    root = (base / (source.get("subpath") or "")).resolve()
    if root != base and base not in root.parents:
        raise SourceError(f"subpath {source.get('subpath')!r} leaves the source")
    return root


def _git_env() -> dict[str, str]:
    """The environment git runs in: never prompting, and authenticated to
    `KB_GIT_TOKEN_HOST` when a token is configured.

    `GIT_CONFIG_*` applies the header to this one invocation, so the token is in neither
    the argument list (visible in `ps`) nor the clone's `.git/config`, and the source's
    stored URL stays credential-free.
    """
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if settings.kb_git_token:
        basic = base64.b64encode(
            f"x-access-token:{settings.kb_git_token}".encode("utf-8")
        ).decode("ascii")
        env.update(
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0=f"http.https://{settings.kb_git_token_host}/.extraheader",
            GIT_CONFIG_VALUE_0=f"Authorization: Basic {basic}",
        )
    return env


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], check=True, capture_output=True, text=True, env=_git_env()
        )
    except subprocess.CalledProcessError as exc:
        # git's own message says what failed (auth, missing ref); the token is not in it.
        raise SourceError(f"git failed: {exc.stderr.strip()}") from exc
    return result.stdout.strip()


def _run_git(repo_path: Path, *args: str) -> str:
    return _git("-C", str(repo_path), *args)


def _ensure_git(source: dict[str, Any]) -> str:
    """Bring the clone to the source's ref; the commit it is now at."""
    repo_path = checkout_path(source)
    if not (repo_path / ".git").exists():
        if repo_path.exists() and any(repo_path.iterdir()):
            raise SourceError(f"{repo_path} exists but is not a git checkout")
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", source["location"], str(repo_path))

    if _run_git(repo_path, "status", "--porcelain"):
        raise SourceError(f"{repo_path} has local changes; refusing to sync")

    _run_git(repo_path, "fetch", "--prune", "origin")
    _run_git(repo_path, "checkout", "--detach", source.get("ref") or "origin/HEAD")
    return _run_git(repo_path, "rev-parse", "HEAD")


def prepare(source: dict[str, Any]) -> tuple[Path, str | None]:
    """The directory to read, and the version it is at (a commit, or none)."""
    version = _ensure_git(source) if source["kind"] == "git" else None
    root = content_root(source)
    if not root.is_dir():
        raise SourceError(f"{root} is not a directory")
    return root, version


def _read_markdown(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("---\n"):
        parts = text.split("\n---\n", 1)
        if len(parts) == 2:
            text = parts[1].strip()
    return text


def _title_from_markdown(path: Path, text: str) -> str:
    for line in text.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return path.stem


def _public_location(rel_path: str) -> str:
    path = Path(rel_path)
    if path.name == "index.md":
        base = path.parent.as_posix()
    else:
        base = path.with_suffix("").as_posix()
    # `Path("index.md").parent` is `.`, which would publish the site root as `./`.
    if base == ".":
        base = ""
    return base + "/"


def read_documents(root: Path) -> list[SourceDocument]:
    docs: list[SourceDocument] = []
    for path in sorted(p for p in root.rglob("*.md") if p.is_file()):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        text = _read_markdown(path)
        if not text:
            continue
        rel_path = rel.as_posix()
        docs.append(
            SourceDocument(
                rel_path=rel_path,
                title=_title_from_markdown(path, text),
                text=text,
                location=_public_location(rel_path),
            )
        )
    return docs


async def ingest(
    source: dict[str, Any],
    root: Path,
    *,
    kb_store: KbStore,
    collection: str,
    full: bool = False,
) -> dict[str, Any]:
    """Bring `collection` in line with what `root` holds now.

    Only changed documents are re-embedded; documents the source no longer has are
    removed. `full` ignores what was recorded and re-embeds everything.
    """
    community_id = source["community_id"]
    previous = {} if full else await kb_store.document_versions(source["id"], collection)
    current: dict[str, str] = {}
    indexed = skipped = removed = 0

    for doc in read_documents(root):
        current[doc.rel_path] = doc.version
        if previous.get(doc.rel_path) == doc.version:
            skipped += 1
            continue
        source_uri = f"kb-source://{source['id']}/{doc.location}"
        await rag.upsert_documents_from_text(
            community_id=community_id,
            text=f"{doc.title}\n\n{doc.text}",
            metadata={
                "kind": "kb_source",
                # A source's citation is not something a reader can follow.
                "hidden": True,
                "source_id": source["id"],
                "source_uri": source_uri,
                "source": source_uri,
                "title": doc.title,
                "location": doc.location,
                "repo_path": doc.rel_path,
            },
            doc_id=source_doc_id(source["id"], doc.rel_path),
            collection=collection,
        )
        indexed += 1

    for rel_path in previous.keys() - current.keys():
        await rag.delete_document(
            source_doc_id(source["id"], rel_path),
            community_id=community_id,
            collection=collection,
        )
        removed += 1

    await kb_store.set_document_versions(source["id"], collection, current)
    return {"indexed": indexed, "skipped": skipped, "removed": removed}


async def sync(
    source: dict[str, Any],
    *,
    kb_store: KbStore,
    collection: str | None = None,
    full: bool = False,
) -> dict[str, Any]:
    """Update the source and import it into the community's live knowledge base, or
    into `collection` when one is being rebuilt."""
    async with _sync_lock:
        root, version = await asyncio.to_thread(prepare, source)
        target = collection or await asyncio.to_thread(
            rag.live_collection, source["community_id"]
        )
        result = await ingest(source, root, kb_store=kb_store, collection=target, full=full)
        await kb_store.mark_synced(source["id"], version)
        log.info(
            "kb_source_synced",
            extra={"source": source["id"], "collection": target, **result},
        )
        return {"source_id": source["id"], "version": version, "collection": target, **result}


async def sync_all(
    *, kb_store: KbStore, community_id: str | None = None, full: bool = False
) -> list[dict[str, Any]]:
    """Sync every registered source, or a community's. One failing source does not
    stop the others; its error is in the result."""
    results: list[dict[str, Any]] = []
    for source in await kb_store.list_sources(community_id):
        try:
            results.append(await sync(source, kb_store=kb_store, full=full))
        except Exception as exc:
            log.exception("kb_source_sync_failed", extra={"source": source["id"]})
            results.append({"source_id": source["id"], "error": str(exc)})
    return results
