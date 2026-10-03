"""`celine-assistant kb`: arguments, output, and exit codes.

What the commands do is tested in `test_kb_admin.py` and `test_kb_sources.py`; this is
the shell around them, run through typer's own runner with the stores replaced.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from celine.assistant import cli, kb_collections
from celine.assistant.settings import settings
from tests.conftest import COMMUNITY, FakeHistoryStore, FakeKbStore

runner = CliRunner()


@pytest.fixture
def stores(memory_qdrant, monkeypatch):
    history, kb_store = FakeHistoryStore(), FakeKbStore()
    monkeypatch.setattr(cli, "HistoryStore", lambda: history)
    monkeypatch.setattr(cli, "KbStore", lambda: kb_store)
    monkeypatch.setattr(cli, "configure_logging", lambda level: None)
    return history, kb_store


def invoke(*args: str):
    result = runner.invoke(cli.app, ["kb", *args])
    return result, (json.loads(result.stdout) if result.exit_code == 0 else None)


# @verifies REQ-0043
def test_a_directory_source_is_registered(stores, tmp_path):
    result, body = invoke("source", "add", "--community", COMMUNITY, "--dir", str(tmp_path))

    assert result.exit_code == 0, result.output
    assert body["kind"] == "dir"
    assert body["location"] == str(tmp_path.resolve())


# @verifies REQ-0043
def test_a_git_source_is_registered_with_its_ref_and_subdirectory(stores):
    result, body = invoke(
        "source", "add", "--community", COMMUNITY,
        "--git", "https://git.example/handbook.git", "--ref", "v2", "--path", "docs",
    )

    assert result.exit_code == 0, result.output
    assert (body["kind"], body["ref"], body["subpath"]) == ("git", "v2", "docs")


@pytest.mark.parametrize(
    "args",
    [
        ["--community", COMMUNITY],
        ["--community", COMMUNITY, "--git", "https://x", "--dir", "/tmp"],
        ["--community", "Not Valid", "--git", "https://x"],
        ["--community", COMMUNITY, "--dir", "/does/not/exist"],
    ],
)
# @verifies REQ-0043
def test_a_source_that_cannot_be_registered_is_refused(stores, args):
    result, _ = invoke("source", "add", *args)

    assert result.exit_code != 0
    assert stores[1].sources == {}


# @verifies REQ-0043
def test_removing_a_source_removes_its_documents(stores, tmp_path):
    history, kb_store = stores
    (tmp_path / "a.md").write_text("# A\n\nBody.")
    _, src = invoke("source", "add", "--community", COMMUNITY, "--dir", str(tmp_path))
    assert invoke("sync")[0].exit_code == 0

    result, _ = invoke("source", "remove", src["id"])

    assert result.exit_code == 0, result.output
    from celine.assistant import rag

    assert rag.indexed_values(kb_collections.alias_name(COMMUNITY), "doc_id") == set()


# @verifies REQ-0033
def test_a_failing_source_makes_the_sync_fail(stores, tmp_path):
    good = tmp_path / "good"
    good.mkdir()
    (good / "a.md").write_text("# A")
    invoke("source", "add", "--community", COMMUNITY, "--dir", str(good))
    _, bad = invoke("source", "add", "--community", COMMUNITY, "--dir", str(tmp_path))
    stores[1].sources[bad["id"]]["location"] = str(tmp_path / "gone")

    result = runner.invoke(cli.app, ["kb", "sync"])

    assert result.exit_code == 1
    body = json.loads(result.stdout)
    assert [("error" in r) for r in body] == [False, True]


@pytest.mark.parametrize("args", [[], ["--community", COMMUNITY, "--all"]])
# @verifies REQ-0041
def test_reindex_needs_exactly_one_target(stores, args):
    assert invoke("reindex", *args)[0].exit_code != 0


# @verifies REQ-0041
def test_reindex_all_rebuilds_every_known_community(stores, tmp_path):
    invoke("source", "add", "--community", COMMUNITY, "--dir", str(tmp_path))
    invoke("source", "add", "--community", "other-rec", "--dir", str(tmp_path))

    result, body = invoke("reindex", "--all")

    assert result.exit_code == 0, result.output
    assert [r["community_id"] for r in body] == [COMMUNITY, "other-rec"]


def test_reindex_can_build_for_a_model_the_service_does_not_use_yet(stores, monkeypatch):
    """@verifies REQ-0041"""
    monkeypatch.setattr(settings, "llm_embed_model", settings.llm_embed_model)
    monkeypatch.setattr(settings, "llm_embed_dimensions", settings.llm_embed_dimensions)

    result, body = invoke(
        "reindex", "--community", COMMUNITY, "--embed-model", "next", "--embed-dimensions", "16"
    )

    assert result.exit_code == 0, result.output
    assert body[0]["alias"] == kb_collections.alias_name(
        COMMUNITY, kb_collections.fingerprint("next", 16)
    )


# @verifies REQ-0041
def test_prune_asks_before_deleting(stores):
    invoke("reindex", "--community", COMMUNITY)
    invoke("reindex", "--community", COMMUNITY)

    refused = runner.invoke(cli.app, ["kb", "prune"], input="n\n")
    assert refused.exit_code != 0

    _, body = invoke("prune", "--dry-run")
    assert len(body["would_delete"]) == 1

    _, body = invoke("prune", "--yes")
    assert len(body["deleted"]) == 1


# @verifies REQ-0042
def test_migrate_legacy_needs_a_community(stores):
    assert invoke("migrate-legacy")[0].exit_code != 0


# @verifies REQ-0041
def test_status_prints_json(stores):
    result, body = invoke("status")

    assert result.exit_code == 0, result.output
    assert body["model"] == settings.llm_embed_model
    assert body["communities"] == []
