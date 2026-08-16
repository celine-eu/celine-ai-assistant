from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from .rag import upsert_documents_from_text
from .settings import settings

log = logging.getLogger(__name__)
_sync_lock = asyncio.Lock()


def docs_repo_path() -> Path:
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
        log.exception("training_materials_manifest_read_failed", extra={"path": path})
        return {}

    repo_docs = payload.get("training_materials") if isinstance(payload, dict) else None
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
            log.exception(
                "training_materials_manifest_merge_failed", extra={"path": path}
            )

    payload["training_materials"] = manifest
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def _run_git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _clone_repo(repo_path: Path) -> None:
    repo_url = settings.training_materials_repo_url.strip()
    if not repo_url:
        raise RuntimeError(
            "TRAINING_MATERIALS_REPO_URL is not configured and repo is missing"
        )

    repo_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", repo_url, str(repo_path)],
        check=True,
        capture_output=True,
        text=True,
    )


def _ensure_repo(target_ref: str | None) -> dict[str, Any]:
    repo_path = docs_repo_path()
    repo_exists = (repo_path / ".git").exists()
    if not repo_exists and repo_path.exists() and any(repo_path.iterdir()):
        raise RuntimeError(
            f"Training materials path exists but is not a git repo: {repo_path}"
        )
    if not repo_exists:
        _clone_repo(repo_path)

    status = _run_git(repo_path, "status", "--porcelain")
    if status:
        raise RuntimeError("Training materials repo has local changes; refusing sync")

    previous_commit = _run_git(repo_path, "rev-parse", "HEAD")
    _run_git(repo_path, "fetch", "--prune", "origin")

    resolved_target = target_ref or settings.training_materials_ref
    _run_git(repo_path, "checkout", "--detach", resolved_target)
    current_commit = _run_git(repo_path, "rev-parse", "HEAD")

    return {
        "repo_path": str(repo_path),
        "target": resolved_target,
        "previous_commit": previous_commit,
        "current_commit": current_commit,
        "updated": previous_commit != current_commit,
    }


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
    # `Path("index.md").parent` is `.`, which would publish the site root as `./` and
    # its citation as `training-materials://.//`.
    if base == ".":
        base = ""
    return base + "/"


async def ingest_training_materials(*, force_full: bool = False) -> dict[str, Any]:
    root = docs_repo_path()
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
                "kind": "training_material",
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


async def sync_training_materials(
    *, target_ref: str | None, force_full: bool = False
) -> dict[str, Any]:
    async with _sync_lock:
        git_result = await asyncio.to_thread(_ensure_repo, target_ref)
        ingest_result = await ingest_training_materials(force_full=force_full)
        return {
            "status": "ok",
            "git": git_result,
            "ingest": ingest_result,
        }


async def startup_sync_training_materials() -> dict[str, Any]:
    repo_url = settings.training_materials_repo_url.strip()
    repo_path = docs_repo_path()
    has_git_repo = (repo_path / ".git").exists()
    has_markdown = repo_path.exists() and any(repo_path.rglob("*.md"))
    if not repo_url and not repo_path.exists():
        return {
            "status": "skipped",
            "reason": "training materials repo path missing and repo url not configured",
            "repo_path": str(repo_path),
        }
    if not repo_url and not has_git_repo and not has_markdown:
        return {
            "status": "skipped",
            "reason": "training materials path is empty and repo url not configured",
            "repo_path": str(repo_path),
        }

    if repo_url and settings.training_materials_sync_on_start:
        return await sync_training_materials(
            target_ref=None, force_full=settings.ingest_force_reload_on_start
        )

    ingest_result = await ingest_training_materials(
        force_full=settings.ingest_force_reload_on_start
    )
    return {
        "status": "ok",
        "git": {
            "repo_path": str(repo_path),
            "target": None,
            "previous_commit": None,
            "current_commit": None,
            "updated": False,
        },
        "ingest": ingest_result,
    }
