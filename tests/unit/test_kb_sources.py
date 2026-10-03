"""Knowledge sources: a git repository or a directory feeding one community.

Qdrant is faked by replacing the two `rag` writes the ingester makes; the git checkout is
real, because `git` is a binary and not a service, and the interesting behaviours here
are exactly the ones that depend on what git reports.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from celine.assistant import kb_sources as ks
from celine.assistant.settings import settings
from tests.conftest import COMMUNITY, FakeKbStore


@pytest.fixture
def written(monkeypatch):
    """Capture what would have gone to, and been removed from, Qdrant."""
    calls: dict[str, list] = {"upserted": [], "deleted": []}

    async def _upsert(*, community_id, text, metadata, doc_id=None, collection=None):
        calls["upserted"].append(
            {
                "community_id": community_id,
                "text": text,
                "metadata": metadata,
                "doc_id": doc_id,
                "collection": collection,
            }
        )
        return {"inserted": 1}

    async def _delete(doc_id, *, community_id, collection=None):
        calls["deleted"].append((community_id, doc_id, collection))

    monkeypatch.setattr(ks.rag, "upsert_documents_from_text", _upsert)
    monkeypatch.setattr(ks.rag, "delete_document", _delete)
    return calls


@pytest.fixture
def docs_dir(tmp_path) -> Path:
    root = tmp_path / "handbook"
    root.mkdir()
    return root


def dir_source(root: Path, **overrides) -> dict:
    return {
        "id": "src-1",
        "community_id": COMMUNITY,
        "kind": "dir",
        "location": str(root),
        "ref": None,
        "subpath": None,
        **overrides,
    }


# --- markdown handling ------------------------------------------------------


# @verifies REQ-0031
def test_yaml_front_matter_is_stripped(tmp_path):
    path = tmp_path / "a.md"
    path.write_text("---\ntitle: Solar\nweight: 3\n---\n# Solar\n\nBody.\n")
    assert ks._read_markdown(path) == "# Solar\n\nBody."


# @verifies REQ-0031
def test_a_document_that_merely_starts_with_a_rule_keeps_its_body(tmp_path):
    path = tmp_path / "a.md"
    path.write_text("---\nnot front matter, never closed\n")
    assert ks._read_markdown(path) == "---\nnot front matter, never closed"


# @verifies REQ-0031
def test_the_title_is_the_first_heading(tmp_path):
    path = tmp_path / "a.md"
    assert ks._title_from_markdown(path, "## Sharing energy\n\n# Later") == "Sharing energy"


# @verifies REQ-0031
def test_without_a_heading_the_title_is_the_filename(tmp_path):
    path = tmp_path / "self-consumption.md"
    assert ks._title_from_markdown(path, "Body only.") == "self-consumption"


@pytest.mark.parametrize(
    ("rel", "location"),
    [
        ("guide/index.md", "guide/"),
        ("guide/solar.md", "guide/solar/"),
        ("solar.md", "solar/"),
        ("index.md", "/"),
    ],
)
# @verifies REQ-0031
def test_a_public_location_is_derived_from_the_repository_path(rel, location):
    assert ks._public_location(rel) == location


# @verifies REQ-0031
def test_hidden_directories_are_not_read(docs_dir):
    (docs_dir / ".github").mkdir()
    (docs_dir / ".github" / "PULL_REQUEST_TEMPLATE.md").write_text("# Template")
    (docs_dir / "solar.md").write_text("# Solar\n\nBody.")

    assert [d.rel_path for d in ks.read_documents(docs_dir)] == ["solar.md"]


# --- incremental ingestion --------------------------------------------------


async def test_every_document_is_indexed_into_the_source_s_community(docs_dir, written):
    """@verifies REQ-0032"""
    (docs_dir / "solar.md").write_text("# Solar\n\nPanels.")
    (docs_dir / "guide").mkdir()
    (docs_dir / "guide" / "index.md").write_text("# Guide\n\nStart here.")

    result = await ks.ingest(
        dir_source(docs_dir), docs_dir, kb_store=FakeKbStore(), collection="gen-1"
    )

    assert result == {"indexed": 2, "skipped": 0, "removed": 0}
    assert {c["community_id"] for c in written["upserted"]} == {COMMUNITY}
    assert {c["collection"] for c in written["upserted"]} == {"gen-1"}
    assert {c["doc_id"] for c in written["upserted"]} == {
        "source:src-1:solar.md",
        "source:src-1:guide/index.md",
    }


async def test_source_material_is_marked_hidden_and_attributed(docs_dir, written):
    """A source's citation is not something a reader can follow, so it is withheld from
    the client; `source_id` is what removing the source deletes by.

    @verifies REQ-0032
    """
    (docs_dir / "solar.md").write_text("# Solar\n\nPanels.")

    await ks.ingest(dir_source(docs_dir), docs_dir, kb_store=FakeKbStore(), collection="g")

    (call,) = written["upserted"]
    assert call["metadata"]["kind"] == "kb_source"
    assert call["metadata"]["hidden"] is True
    assert call["metadata"]["source_id"] == "src-1"
    assert call["text"].startswith("Solar\n\n")


async def test_an_unchanged_document_is_skipped_on_the_next_run(docs_dir, written):
    """@verifies REQ-0032"""
    (docs_dir / "solar.md").write_text("# Solar\n\nPanels.")
    store = FakeKbStore()
    await ks.ingest(dir_source(docs_dir), docs_dir, kb_store=store, collection="g")

    result = await ks.ingest(dir_source(docs_dir), docs_dir, kb_store=store, collection="g")

    assert result == {"indexed": 0, "skipped": 1, "removed": 0}


async def test_what_was_recorded_for_one_collection_says_nothing_of_another(
    docs_dir, written
):
    """A rebuild writes a new generation; it must start from nothing, or it would skip
    every document the old generation already had.

    @verifies REQ-0032 @verifies REQ-0041
    """
    (docs_dir / "solar.md").write_text("# Solar\n\nPanels.")
    store = FakeKbStore()
    await ks.ingest(dir_source(docs_dir), docs_dir, kb_store=store, collection="old")

    result = await ks.ingest(dir_source(docs_dir), docs_dir, kb_store=store, collection="new")

    assert result["indexed"] == 1


async def test_an_edited_document_is_re_indexed(docs_dir, written):
    """@verifies REQ-0032"""
    doc = docs_dir / "solar.md"
    doc.write_text("# Solar\n\nPanels.")
    store = FakeKbStore()
    await ks.ingest(dir_source(docs_dir), docs_dir, kb_store=store, collection="g")

    doc.write_text("# Solar\n\nPanels and inverters.")
    result = await ks.ingest(dir_source(docs_dir), docs_dir, kb_store=store, collection="g")

    assert result["indexed"] == 1
    assert written["upserted"][-1]["doc_id"] == "source:src-1:solar.md"


async def test_a_document_the_source_no_longer_has_is_removed(docs_dir, written):
    """Before sources, a deleted page stayed retrievable for as long as the collection
    did.

    @verifies REQ-0032
    """
    (docs_dir / "solar.md").write_text("# Solar\n\nPanels.")
    (docs_dir / "wind.md").write_text("# Wind\n\nTurbines.")
    store = FakeKbStore()
    await ks.ingest(dir_source(docs_dir), docs_dir, kb_store=store, collection="g")

    (docs_dir / "wind.md").unlink()
    result = await ks.ingest(dir_source(docs_dir), docs_dir, kb_store=store, collection="g")

    assert result["removed"] == 1
    assert written["deleted"] == [(COMMUNITY, "source:src-1:wind.md", "g")]


async def test_a_full_run_ignores_what_was_recorded(docs_dir, written):
    """@verifies REQ-0032"""
    (docs_dir / "solar.md").write_text("# Solar\n\nPanels.")
    store = FakeKbStore()
    await ks.ingest(dir_source(docs_dir), docs_dir, kb_store=store, collection="g")

    result = await ks.ingest(
        dir_source(docs_dir), docs_dir, kb_store=store, collection="g", full=True
    )

    assert result["indexed"] == 1


async def test_an_empty_document_is_neither_indexed_nor_counted(docs_dir, written):
    """@verifies REQ-0032"""
    (docs_dir / "empty.md").write_text("   \n")

    result = await ks.ingest(dir_source(docs_dir), docs_dir, kb_store=FakeKbStore(), collection="g")

    assert result == {"indexed": 0, "skipped": 0, "removed": 0}


# --- where a source is read from --------------------------------------------


# @verifies REQ-0033
def test_a_directory_source_is_read_where_it_is(docs_dir):
    root, version = ks.prepare(dir_source(docs_dir))

    assert root == docs_dir.resolve()
    assert version is None


# @verifies REQ-0033
def test_a_missing_directory_is_an_error_not_an_empty_run(tmp_path):
    with pytest.raises(ks.SourceError, match="not a directory"):
        ks.prepare(dir_source(tmp_path / "gone"))


# @verifies REQ-0033
def test_a_subpath_may_not_leave_the_source(docs_dir):
    with pytest.raises(ks.SourceError, match="leaves the source"):
        ks.content_root(dir_source(docs_dir, subpath="../elsewhere"))


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def upstream(tmp_path) -> Path:
    """A repository to clone from, with the documents under `docs/`."""
    repo = tmp_path / "upstream"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.test")
    git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("# Not documentation")
    (repo / "docs").mkdir()
    (repo / "docs" / "solar.md").write_text("# Solar\n\nHow it works.")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "initial")
    return repo


@pytest.fixture
def clones(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "clones"
    monkeypatch.setattr(settings, "kb_sources_dir", str(root))
    return root


def git_source(upstream: Path, **overrides) -> dict:
    return {
        "id": "src-git",
        "community_id": COMMUNITY,
        "kind": "git",
        "location": str(upstream),
        "ref": None,
        "subpath": "docs",
        **overrides,
    }


# @verifies REQ-0033
def test_a_git_source_is_cloned_and_read_from_its_subdirectory(upstream, clones):
    root, version = ks.prepare(git_source(upstream))

    assert root == clones / "src-git" / "docs"
    assert version == git(upstream, "rev-parse", "HEAD")
    assert [d.rel_path for d in ks.read_documents(root)] == ["solar.md"]


# @verifies REQ-0033
def test_a_git_source_follows_its_ref(upstream, clones):
    first = git(upstream, "rev-parse", "HEAD")
    (upstream / "docs" / "wind.md").write_text("# Wind")
    git(upstream, "add", ".")
    git(upstream, "commit", "-qm", "wind")

    _, version = ks.prepare(git_source(upstream, ref=first))
    assert version == first

    _, version = ks.prepare(git_source(upstream))
    assert version == git(upstream, "rev-parse", "HEAD")


def test_a_clone_with_local_changes_refuses_to_sync(upstream, clones):
    """A sync is `git checkout --detach`, which would discard the edit. Refusing is the
    protection; there is nothing else stopping it.

    @verifies REQ-0033
    """
    ks.prepare(git_source(upstream))
    (clones / "src-git" / "docs" / "solar.md").write_text("# Solar\n\nEdited in place.")

    with pytest.raises(ks.SourceError, match="local changes"):
        ks.prepare(git_source(upstream))


# @verifies REQ-0033
def test_a_non_empty_directory_that_is_not_a_clone_refuses_to_sync(upstream, clones):
    (clones / "src-git").mkdir(parents=True)
    (clones / "src-git" / "stray.md").write_text("# Stray")

    with pytest.raises(ks.SourceError, match="not a git checkout"):
        ks.prepare(git_source(upstream))


# --- startup ----------------------------------------------------------------


def test_leftover_training_materials_settings_are_reported(monkeypatch):
    """They are read by nothing now. Reported rather than refused: the service runs
    without them, and a deployment's chart may still set them.

    @verifies REQ-0033
    """
    monkeypatch.setattr(settings, "removed_training_materials_repo_url", "https://git.example/x")

    assert ks.removed_ingestion_settings(settings) == ["TRAINING_MATERIALS_REPO_URL"]


# --- private sources ----------------------------------------------------------


def test_without_a_token_git_runs_unauthenticated_and_never_prompts(monkeypatch):
    """A prompt would hang a sync forever waiting on a terminal it does not have.

    @verifies REQ-0044
    """
    monkeypatch.setattr(settings, "kb_git_token", "")

    env = ks._git_env()

    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "GIT_CONFIG_COUNT" not in env


def test_a_token_is_an_environment_header_for_its_host_only(monkeypatch):
    """Not a URL credential (stored in the database, printed by `kb source list`), not
    an argument (visible in `ps`), not the clone's `.git/config`.

    @verifies REQ-0044
    """
    import base64

    monkeypatch.setattr(settings, "kb_git_token", "tok-123")
    monkeypatch.setattr(settings, "kb_git_token_host", "github.com")

    env = ks._git_env()

    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    expected = base64.b64encode(b"x-access-token:tok-123").decode()
    assert env["GIT_CONFIG_VALUE_0"] == f"Authorization: Basic {expected}"


def test_a_token_never_lands_in_the_clone_s_config(upstream, clones, monkeypatch):
    """@verifies REQ-0044"""
    monkeypatch.setattr(settings, "kb_git_token", "tok-123")

    ks.prepare(git_source(upstream))

    config = (clones / "src-git" / ".git" / "config").read_text()
    assert "tok-123" not in config
    assert "extraheader" not in config


def test_a_failing_git_command_is_a_source_error_with_git_s_reason(clones, tmp_path):
    """@verifies REQ-0033"""
    with pytest.raises(ks.SourceError, match="git failed"):
        ks.prepare(git_source(tmp_path / "no-such-repo"))
