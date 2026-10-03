"""`celine-assistant` — operator commands, run in the service image.

    celine-assistant kb status
    celine-assistant kb source add --community example-rec --git https://… [--ref R] [--path docs]
    celine-assistant kb source add --community example-rec --dir /data/handbook
    celine-assistant kb sync [--community X] [--source ID] [--full]
    celine-assistant kb reindex (--community X | --all) [--re-extract] [--embed-model M --embed-dimensions N]
    celine-assistant kb prune [--keep N] [--legacy] [--dry-run]
    celine-assistant kb migrate-legacy --community X [--git URL] [--dry-run]

Every command prints JSON. Needs what the service needs: `DATABASE_URL`, `QDRANT_*`,
`LLM_EMBED_*`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import typer

from . import kb_admin, kb_collections, kb_sources, rag
from .history import HistoryStore
from .kb_store import KbStore
from .logging_ import configure_logging
from .settings import settings

app = typer.Typer(no_args_is_help=True, help="CELINE AI assistant operations.")
kb = typer.Typer(no_args_is_help=True, help="Per-community knowledge bases.")
source = typer.Typer(no_args_is_help=True, help="Registered knowledge sources.")
app.add_typer(kb, name="kb")
kb.add_typer(source, name="source")


def _print(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _run(fn: Callable[[HistoryStore, KbStore], Awaitable[Any]]) -> Any:
    """Run one command against the real stores, and release the pool afterwards."""
    configure_logging(settings.log_level)

    async def _main() -> Any:
        from .db import engine

        try:
            return await fn(HistoryStore(), KbStore())
        finally:
            await engine.dispose()

    return asyncio.run(_main())


def _community(value: str) -> str:
    try:
        return kb_collections.validate_community_id(value)
    except kb_collections.InvalidCommunityId as exc:
        raise typer.BadParameter(str(exc)) from exc


@kb.command("status")
def status_cmd(
    community: Optional[str] = typer.Option(None, help="Only this community."),
) -> None:
    """Every knowledge base: alias, generation, points, sources, attachments."""

    async def _go(history: HistoryStore, kb_store: KbStore) -> Any:
        report = await kb_admin.status(history, kb_store)
        if community:
            report["communities"] = [
                c for c in report["communities"] if c["community_id"] == community
            ]
        return report

    _print(_run(_go))


@source.command("add")
def source_add(
    community: str = typer.Option(..., help="The community (REC organization alias)."),
    git: Optional[str] = typer.Option(None, help="A git URL to clone."),
    ref: Optional[str] = typer.Option(None, help="Branch, tag or commit; origin/HEAD by default."),
    path: Optional[str] = typer.Option(None, help="Read only this subdirectory of the repository."),
    dir: Optional[Path] = typer.Option(None, "--dir", help="A local directory instead of git."),
) -> None:
    """Register a source for a community. Nothing is imported until `kb sync`."""
    _community(community)
    if bool(git) == bool(dir):
        raise typer.BadParameter("give exactly one of --git or --dir")
    if dir and (ref or path):
        raise typer.BadParameter("--ref and --path apply to --git only")
    if dir and not dir.is_dir():
        raise typer.BadParameter(f"{dir} is not a directory")

    async def _go(history: HistoryStore, kb_store: KbStore) -> Any:
        return await kb_store.add_source(
            community_id=community,
            kind="git" if git else "dir",
            location=git or str(dir.resolve()),
            ref=ref,
            subpath=path,
        )

    _print(_run(_go))


@source.command("list")
def source_list(community: Optional[str] = typer.Option(None)) -> None:
    async def _go(history: HistoryStore, kb_store: KbStore) -> Any:
        return await kb_store.list_sources(community)

    _print(_run(_go))


@source.command("remove")
def source_remove(source_id: str) -> None:
    """Unregister a source and remove its documents from the live knowledge base."""

    async def _go(history: HistoryStore, kb_store: KbStore) -> Any:
        found = await kb_store.get_source(source_id)
        if not found:
            raise typer.BadParameter(f"no source {source_id}")
        alias = kb_collections.alias_name(found["community_id"])
        if await asyncio.to_thread(rag.qdrant().collection_exists, alias):
            await asyncio.to_thread(rag.delete_where, alias, "source_id", source_id)
        return await kb_store.remove_source(source_id)

    _print(_run(_go))


@kb.command("sync")
def sync_cmd(
    community: Optional[str] = typer.Option(None),
    source_id: Optional[str] = typer.Option(None, "--source"),
    full: bool = typer.Option(False, help="Re-embed every document, changed or not."),
) -> None:
    """Pull the sources and import what changed into the live knowledge bases."""

    async def _go(history: HistoryStore, kb_store: KbStore) -> Any:
        if source_id:
            found = await kb_store.get_source(source_id)
            if not found:
                raise typer.BadParameter(f"no source {source_id}")
            return [await kb_sources.sync(found, kb_store=kb_store, full=full)]
        return await kb_sources.sync_all(kb_store=kb_store, community_id=community, full=full)

    results = _run(_go)
    _print(results)
    if any("error" in r for r in results):
        raise typer.Exit(1)


@kb.command("reindex")
def reindex_cmd(
    community: Optional[str] = typer.Option(None),
    all_: bool = typer.Option(False, "--all", help="Every known community."),
    re_extract: bool = typer.Option(
        False, help="Run extraction and image captioning on the stored files again."
    ),
    dry_run: bool = typer.Option(False),
    embed_model: Optional[str] = typer.Option(
        None, help="Build for this embedding model instead of LLM_EMBED_MODEL."
    ),
    embed_dimensions: Optional[int] = typer.Option(None),
) -> None:
    """Build a new generation from the sources and attachments, then move the alias.

    With --embed-model, the knowledge bases for a model the service does not use yet are
    built beside the current ones; deploying with that model is the switch.
    """
    if bool(community) == all_:
        raise typer.BadParameter("give exactly one of --community or --all")
    if community:
        _community(community)
    if embed_model:
        settings.llm_embed_model = embed_model
        settings.llm_embed_dimensions = embed_dimensions
        rag.reset_indexes()
    elif embed_dimensions:
        raise typer.BadParameter("--embed-dimensions goes with --embed-model")

    async def _go(history: HistoryStore, kb_store: KbStore) -> Any:
        targets = [community] if community else await kb_admin.communities(history, kb_store)
        results = []
        for target in targets:
            try:
                results.append(
                    await kb_admin.reindex(
                        target,
                        history=history,
                        kb_store=kb_store,
                        re_extract=re_extract,
                        dry_run=dry_run,
                    )
                )
            except Exception as exc:
                results.append({"community_id": target, "error": str(exc)})
        return results

    results = _run(_go)
    _print(results)
    if any("error" in r for r in results):
        raise typer.Exit(1)


@kb.command("prune")
def prune_cmd(
    keep: int = typer.Option(0, help="Unaliased generations to keep per community and model."),
    legacy: bool = typer.Option(
        False, help="Also delete the collection used before knowledge bases were per community."
    ),
    dry_run: bool = typer.Option(False),
    yes: bool = typer.Option(False, "--yes", help="Do not ask for confirmation."),
) -> None:
    """Delete collections no alias points to."""

    async def _plan(history: HistoryStore, kb_store: KbStore) -> Any:
        return await kb_admin.prune(kb_store=kb_store, keep=keep, legacy=legacy, dry_run=True)

    doomed = _run(_plan)
    if dry_run or not doomed:
        _print({"would_delete" if dry_run else "deleted": doomed})
        return
    if not yes:
        typer.confirm(f"Delete {len(doomed)} collection(s): {', '.join(doomed)}?", abort=True)

    async def _go(history: HistoryStore, kb_store: KbStore) -> Any:
        return await kb_admin.prune(kb_store=kb_store, keep=keep, legacy=legacy)

    _print({"deleted": _run(_go)})


@kb.command("migrate-legacy")
def migrate_legacy_cmd(
    community: str = typer.Option(..., help="The community legacy data belongs to."),
    git: Optional[str] = typer.Option(
        None, help="The training-materials repository; TRAINING_MATERIALS_REPO_URL by default."
    ),
    ref: Optional[str] = typer.Option(None),
    path: Optional[str] = typer.Option(None),
    dry_run: bool = typer.Option(False),
) -> None:
    """One-off: assign every attachment with no community to this one, register the
    training-materials repository as its source, and rebuild it."""
    _community(community)

    async def _go(history: HistoryStore, kb_store: KbStore) -> Any:
        return await kb_admin.migrate_legacy(
            community,
            history=history,
            kb_store=kb_store,
            git_url=git,
            ref=ref,
            subpath=path,
            dry_run=dry_run,
        )

    _print(_run(_go))
