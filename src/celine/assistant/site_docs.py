from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from .rag import upsert_documents_from_text
from .settings import settings

log = logging.getLogger(__name__)


def _docs_root() -> Path:
    return Path(settings.training_materials_path).resolve()


def _manifest_key(path: str) -> str:
    return path


def _load_manifest() -> dict[str, str]:
    path = settings.manifest_path
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        log.exception("site_docs_manifest_read_failed", extra={"path": path})
        return {}

    repo_docs = payload.get("site_docs") if isinstance(payload, dict) else None
    if not isinstance(repo_docs, dict):
        return {}
    return {str(k): str(v) for k, v in repo_docs.items()}


def _save_manifest(manifest: dict[str, str]) -> None:
    path = settings.manifest_path
    payload: dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                current = json.load(fh)
            if isinstance(current, dict):
                payload = current
        except Exception:
            log.exception("site_docs_manifest_merge_failed", extra={"path": path})

    payload["site_docs"] = manifest
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def _doc_version(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iter_markdown_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.md") if p.is_file())


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
    return base + "/"


async def sync_site_docs(*, force_full: bool = False) -> dict[str, Any]:
    root = _docs_root()
    if not root.exists():
        raise FileNotFoundError(str(root))
    manifest = {} if force_full else _load_manifest()
    updated_manifest = dict(manifest)
    markdown_files = _iter_markdown_files(root)

    indexed = 0
    skipped = 0

    for path in markdown_files:
        rel_path = path.relative_to(root).as_posix()
        text = _read_markdown(path)
        if not text:
            continue
        title = _title_from_markdown(path, text)
        location = _public_location(rel_path)
        version = _doc_version(text)
        key = _manifest_key(rel_path)
        if not force_full and manifest.get(key) == version:
            skipped += 1
            continue

        source_uri = f"training-materials://{location}"
        await upsert_documents_from_text(
            text=f"{title}\n\n{text}",
            metadata={
                "kind": "site_doc",
                "hidden": True,
                "source_uri": source_uri,
                "source": source_uri,
                "title": title,
                "location": location,
                "repo_path": rel_path,
            },
        )
        updated_manifest[key] = version
        indexed += 1

    _save_manifest(updated_manifest)
    return {
        "status": "ok",
        "root": str(root),
        "indexed": indexed,
        "skipped": skipped,
    }
