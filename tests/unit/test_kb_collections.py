"""Naming, aliases and the startup check, against `qdrant-client`'s local mode."""

from __future__ import annotations

import pytest

from celine.assistant import kb_collections as kc
from celine.assistant.settings import settings


@pytest.fixture
def client(memory_qdrant):
    return memory_qdrant.client


# --- names ------------------------------------------------------------------


@pytest.mark.parametrize("good", ["example-rec", "rec_01", "a", "x-y_z9"])
# @verifies REQ-0041
def test_a_community_id_that_can_name_a_collection_is_kept_as_is(good):
    assert kc.validate_community_id(good) == good


@pytest.mark.parametrize(
    "bad", ["Example-Rec", "rec__x", "-rec", "rec x", "rec/x", "", "a" * 65, None]
)
def test_a_community_id_that_would_need_changing_is_refused(bad):
    """Never normalised: two communities that normalise alike would share a knowledge
    base. `__` is refused because it separates the parts of a name.

    @verifies REQ-0041
    """
    with pytest.raises(kc.InvalidCommunityId):
        kc.validate_community_id(bad)


def test_the_fingerprint_changes_with_the_model_and_the_size():
    """It is what keeps two models' vectors apart.

    @verifies REQ-0041
    """
    base = kc.fingerprint("model-a", 768)
    assert kc.fingerprint("model-a", 768) == base
    assert kc.fingerprint("model-b", 768) != base
    assert kc.fingerprint("model-a", 1024) != base


# @verifies REQ-0041
def test_names_parse_back_into_their_parts():
    alias = kc.alias_name("example-rec", "0123456789")
    assert alias == f"{settings.qdrant_collection}__example-rec__0123456789"

    generation = kc.generation_name(alias, now=0)
    parsed = kc.parse_name(generation)
    assert (parsed.community_id, parsed.fingerprint, parsed.generation) == (
        "example-rec",
        "0123456789",
        "19700101000000",
    )
    assert parsed.alias == alias
    assert kc.parse_name(alias).generation is None


# @verifies REQ-0041
def test_a_name_this_module_did_not_make_is_not_parsed():
    assert kc.parse_name(settings.qdrant_collection) is None
    assert kc.parse_name("somebody_else__x__0123456789") is None
    assert kc.parse_name(f"{settings.qdrant_collection}__x__short") is None


# --- aliases ----------------------------------------------------------------


# @verifies REQ-0041
def test_the_first_write_creates_a_generation_behind_an_alias(client):
    alias = kc.ensure_alias(client, "example-rec")

    collection = kc.aliases(client)[alias]
    assert kc.parse_name(collection).generation
    assert kc.vector_size(client, collection) == settings.llm_embed_dimensions
    assert kc.ensure_alias(client, "example-rec") == alias
    assert kc.generations(client) == [collection]


def test_moving_an_alias_is_one_step_and_reports_where_it_was(client):
    """Delete and create travel in one request, so no reader sees the alias missing.

    @verifies REQ-0041
    """
    alias = kc.ensure_alias(client, "example-rec")
    old = kc.aliases(client)[alias]
    new = kc.create_generation(client, "example-rec")

    assert kc.point_alias(client, alias, new) == old
    assert kc.aliases(client)[alias] == new
    assert set(kc.generations(client)) == {old, new}


# --- startup ----------------------------------------------------------------


# @verifies REQ-0041
def test_startup_passes_when_nothing_exists_yet(client):
    kc.check_startup(client)


def test_startup_refuses_when_a_community_has_knowledge_only_for_another_model(
    client, monkeypatch
):
    """Serving on would answer from nothing, and the next upload would start an empty
    knowledge base beside the real one.

    @verifies REQ-0041
    """
    kc.ensure_alias(client, "example-rec")
    monkeypatch.setattr(settings, "llm_embed_model", "a-new-model")

    with pytest.raises(RuntimeError, match="kb reindex --all"):
        kc.check_startup(client)


def test_startup_passes_once_the_new_model_s_knowledge_is_built(client, monkeypatch):
    """`kb reindex --embed-model` builds the new aliases beside the old ones before the
    deploy; the service on either model then finds its own.

    @verifies REQ-0041
    """
    kc.ensure_alias(client, "example-rec")
    monkeypatch.setattr(settings, "llm_embed_model", "a-new-model")
    kc.ensure_alias(client, "example-rec")

    kc.check_startup(client)
