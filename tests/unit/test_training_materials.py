"""Training-material ingestion.

Qdrant is faked by replacing `upsert_documents_from_text`; the git checkout is real,
because `git` is a binary and not a service, and the interesting behaviours here are
exactly the ones that depend on what git reports.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from celine.assistant import training_materials as tm
from celine.assistant.settings import settings


@pytest.fixture
def materials(tmp_path, monkeypatch):
    root = tmp_path / "materials"
    root.mkdir()
    monkeypatch.setattr(settings, "training_materials_path", str(root))
    monkeypatch.setattr(settings, "manifest_path", str(tmp_path / "manifest.json"))
    return root


@pytest.fixture
def indexed(monkeypatch):
    """Capture what would have gone to Qdrant."""
    calls: list[dict] = []

    async def _upsert(*, text: str, metadata: dict):
        calls.append({"text": text, "metadata": metadata})
        return {"inserted": 1}

    monkeypatch.setattr(tm, "upsert_documents_from_text", _upsert)
    return calls


# --- markdown handling ------------------------------------------------------


# @verifies REQ-0031
def test_yaml_front_matter_is_stripped(tmp_path):
    path = tmp_path / "a.md"
    path.write_text("---\ntitle: Solar\nweight: 3\n---\n# Solar\n\nBody.\n")
    assert tm._read_markdown(path) == "# Solar\n\nBody."


# @verifies REQ-0031
def test_a_document_that_merely_starts_with_a_rule_keeps_its_body(tmp_path):
    path = tmp_path / "a.md"
    path.write_text("---\nnot front matter, never closed\n")
    assert tm._read_markdown(path) == "---\nnot front matter, never closed"


# @verifies REQ-0031
def test_the_title_is_the_first_heading(tmp_path):
    path = tmp_path / "a.md"
    assert tm._title_from_markdown(path, "## Sharing energy\n\n# Later") == "Sharing energy"


# @verifies REQ-0031
def test_without_a_heading_the_title_is_the_filename(tmp_path):
    path = tmp_path / "self-consumption.md"
    assert tm._title_from_markdown(path, "Body only.") == "self-consumption"


@pytest.mark.parametrize(
    ("rel", "location"),
    [
        ("guide/index.md", "guide/"),
        ("guide/solar.md", "guide/solar/"),
        ("solar.md", "solar/"),
    ],
)
def test_a_public_location_is_derived_from_the_repository_path(rel, location):
    """This is what the citation links to on the docs site, so it has to match the
    site's own routing rather than the file layout.

    @verifies REQ-0031
    """
    assert tm._public_location(rel) == location


def test_the_root_index_page_is_the_site_root():
    """`Path("index.md").parent` is `.`, which would publish as `./` and cite as
    `training-materials://.//`. It is normalised away.

    @verifies REQ-0031
    """
    assert tm._public_location("index.md") == "/"


# --- incremental ingestion --------------------------------------------------


# @verifies REQ-0032
async def test_every_markdown_file_is_indexed_once(materials, indexed):
    (materials / "solar.md").write_text("# Solar\n\nHow it works.")
    (materials / "guide").mkdir()
    (materials / "guide" / "index.md").write_text("# Guide\n\nStart here.")

    result = await tm.ingest_training_materials()

    assert result["indexed"] == 2
    assert result["skipped"] == 0
    assert len(indexed) == 2


async def test_indexed_material_is_marked_hidden(materials, indexed):
    """Training material is context for the model, not a citation for the reader; the
    `hidden` flag is what keeps it out of the `sources` event.

    @verifies REQ-0022
    """
    (materials / "solar.md").write_text("# Solar\n\nHow it works.")
    await tm.ingest_training_materials()

    (call,) = indexed
    assert call["metadata"]["hidden"] is True
    assert call["metadata"]["kind"] == "training_material"
    assert call["metadata"]["source_uri"] == "training-materials://solar/"
    assert call["text"].startswith("Solar\n\n# Solar")


# @verifies REQ-0032
async def test_an_unchanged_document_is_skipped_on_the_next_run(materials, indexed):
    (materials / "solar.md").write_text("# Solar\n\nHow it works.")
    await tm.ingest_training_materials()
    indexed.clear()

    result = await tm.ingest_training_materials()

    assert result == {**result, "indexed": 0, "skipped": 1}
    assert indexed == []


async def test_an_edited_document_is_re_indexed(materials, indexed):
    """The manifest keys on a hash of the content, so a touched-but-unchanged file
    stays skipped and an edit anywhere in the body does not.

    @verifies REQ-0032
    """
    (materials / "solar.md").write_text("# Solar\n\nHow it works.")
    await tm.ingest_training_materials()
    indexed.clear()

    (materials / "solar.md").write_text("# Solar\n\nHow it really works.")
    result = await tm.ingest_training_materials()

    assert result["indexed"] == 1
    assert len(indexed) == 1


# @verifies REQ-0032
async def test_a_forced_run_ignores_the_manifest(materials, indexed):
    (materials / "solar.md").write_text("# Solar\n\nHow it works.")
    await tm.ingest_training_materials()
    indexed.clear()

    result = await tm.ingest_training_materials(force_full=True)

    assert result["indexed"] == 1
    assert len(indexed) == 1


# @verifies REQ-0032
async def test_an_empty_document_is_neither_indexed_nor_counted(materials, indexed):
    (materials / "empty.md").write_text("   \n")
    result = await tm.ingest_training_materials()

    assert result["indexed"] == 0
    assert result["skipped"] == 0
    assert indexed == []


async def test_the_manifest_shares_one_file_with_the_other_ingesters(materials, indexed):
    """`site_docs.py` writes its own key into the same JSON document, so a save has to
    merge rather than replace.

    @verifies REQ-0032
    """
    manifest_path = Path(settings.manifest_path)
    manifest_path.write_text(json.dumps({"site_docs": {"other.md": "deadbeef"}}))

    (materials / "solar.md").write_text("# Solar\n\nHow it works.")
    await tm.ingest_training_materials()

    saved = json.loads(manifest_path.read_text())
    assert saved["site_docs"] == {"other.md": "deadbeef"}
    assert "solar.md" in saved["training_materials"]


# @verifies REQ-0033
async def test_a_missing_checkout_is_an_error_not_an_empty_run(materials, indexed):
    for child in materials.iterdir():
        child.unlink()
    materials.rmdir()

    with pytest.raises(FileNotFoundError):
        await tm.ingest_training_materials()


# --- git preconditions ------------------------------------------------------


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def materials_repo(materials):
    git(materials, "init", "-q")
    git(materials, "config", "user.email", "test@example.test")
    git(materials, "config", "user.name", "test")
    (materials / "solar.md").write_text("# Solar\n\nHow it works.")
    git(materials, "add", ".")
    git(materials, "commit", "-qm", "initial")
    return materials


def test_a_checkout_with_local_changes_refuses_to_sync(materials_repo):
    """A sync is `git checkout --detach`, which would discard the edit. Refusing is the
    protection; there is nothing else stopping it.

    @verifies REQ-0033
    """
    (materials_repo / "solar.md").write_text("# Solar\n\nEdited in place.")

    with pytest.raises(RuntimeError, match="local changes"):
        tm._ensure_repo(None)


# @verifies REQ-0033
def test_a_non_empty_directory_that_is_not_a_checkout_refuses_to_sync(materials):
    (materials / "stray.md").write_text("# Stray")

    with pytest.raises(RuntimeError, match="not a git repo"):
        tm._ensure_repo(None)


# @verifies REQ-0033
def test_an_empty_directory_with_no_url_configured_cannot_clone(materials, monkeypatch):
    monkeypatch.setattr(settings, "training_materials_repo_url", "")

    with pytest.raises(RuntimeError, match="TRAINING_MATERIALS_REPO_URL"):
        tm._ensure_repo(None)


async def test_startup_skips_quietly_when_there_is_nothing_to_ingest(
    materials, monkeypatch
):
    """A deployment with neither a checkout nor a URL must still boot.

    @verifies REQ-0033
    """
    monkeypatch.setattr(settings, "training_materials_repo_url", "")

    result = await tm.startup_sync_training_materials()
    assert result["status"] == "skipped"


# @verifies REQ-0033
async def test_startup_ingests_an_existing_checkout_without_touching_git(
    materials_repo, indexed, monkeypatch
):
    monkeypatch.setattr(settings, "training_materials_repo_url", "")

    result = await tm.startup_sync_training_materials()

    assert result["status"] == "ok"
    assert result["git"]["current_commit"] is None
    assert result["ingest"]["indexed"] == 1
