from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

from .site_docs import sync_site_docs
from .settings import settings

_sync_lock = asyncio.Lock()


def docs_repo_path() -> Path:
    return Path(settings.training_materials_path)


def _run_git(*args: str) -> str:
    repo_path = docs_repo_path()
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _sync_repo(target_ref: str | None) -> dict[str, Any]:
    repo_path = docs_repo_path()
    if not (repo_path / ".git").exists():
        raise RuntimeError(f"Training materials repo not found at {repo_path}")

    status = _run_git("status", "--porcelain")
    if status:
        raise RuntimeError("Training materials repo has local changes; refusing sync")

    previous_commit = _run_git("rev-parse", "HEAD")
    _run_git("fetch", "--prune", "origin")

    resolved_target = target_ref or "origin/main"
    _run_git("checkout", "--detach", resolved_target)
    current_commit = _run_git("rev-parse", "HEAD")

    return {
        "repo_path": str(repo_path),
        "target": resolved_target,
        "previous_commit": previous_commit,
        "current_commit": current_commit,
        "updated": previous_commit != current_commit,
    }


async def sync_training_materials(*, target_ref: str | None) -> dict[str, Any]:
    async with _sync_lock:
        git_result = await asyncio.to_thread(_sync_repo, target_ref)
        ingest_result = await sync_site_docs(force_full=False)
        return {
            "status": "ok",
            "git": git_result,
            "ingest": ingest_result,
        }
