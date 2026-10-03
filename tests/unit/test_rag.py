"""Retrieval scoping and index writes, run by a real Qdrant engine.

`qdrant-client`'s local mode evaluates the payload filter itself, so this is the filter
`rag.visibility_filter` builds actually being applied — what the suite could only assume
before. Embeddings are all alike (`MockEmbedding`), so these say what may come back,
never in which order.
"""

from __future__ import annotations

import pytest

from celine.assistant import kb_collections, rag
from tests.conftest import COMMUNITY, OTHER_COMMUNITY


async def put(community_id, text, doc_id, **metadata):
    await rag.upsert_documents_from_text(
        community_id=community_id, text=text, metadata=metadata, doc_id=doc_id
    )


def titles(community_id, user_id, top_k=20) -> set[str]:
    retriever = rag.build_retriever(top_k, user_id=user_id, community_id=community_id)
    nodes = rag.retrieve(
        retriever, "anything", top_k, user_id=user_id, community_id=community_id
    )
    return {n.metadata["title"] for n in nodes}


@pytest.fixture
async def two_communities(memory_qdrant):
    await put(COMMUNITY, "Our handbook", "d1", title="handbook", scope="system")
    await put(COMMUNITY, "Our guide", "d2", title="guide", kind="kb_source")
    await put(COMMUNITY, "Alice's bill", "d3", title="alice-bill", scope="user", owner_user_id="alice")
    await put(COMMUNITY, "Bob's bill", "d4", title="bob-bill", scope="user", owner_user_id="bob")
    await put(COMMUNITY, "Unscoped", "d5", title="unscoped", kind="something-new")
    await put(OTHER_COMMUNITY, "Their handbook", "d6", title="theirs", scope="system")
    return memory_qdrant


async def test_a_member_reads_their_community_s_knowledge_and_their_own_uploads(
    two_communities,
):
    """@verifies REQ-0022"""
    assert titles(COMMUNITY, "alice") == {"handbook", "guide", "alice-bill"}


async def test_another_community_s_knowledge_base_is_not_searched(two_communities):
    """@verifies REQ-0022"""
    assert titles(OTHER_COMMUNITY, "alice") == {"theirs"}


async def test_a_document_this_code_did_not_scope_is_not_returned(two_communities):
    """Deny by default: a fourth kind of document stays invisible until the rule
    accounts for it.

    @verifies REQ-0022
    """
    assert "unscoped" not in titles(COMMUNITY, "alice")


async def test_a_point_in_the_wrong_collection_is_still_not_returned(two_communities):
    """The `community_id` term is in the filter as well as in the collection name.

    @verifies REQ-0022
    """
    client = two_communities.client
    ours = kb_collections.alias_name(COMMUNITY)
    theirs_collection = kb_collections.aliases(client)[kb_collections.alias_name(OTHER_COMMUNITY)]
    points, _ = client.scroll(theirs_collection, limit=10, with_vectors=True)
    client.upsert(ours, points=points)

    assert "theirs" not in titles(COMMUNITY, "alice")


async def test_without_a_community_nothing_is_retrieved(two_communities):
    """@verifies REQ-0022"""
    assert rag.build_retriever(5, user_id="alice", community_id=None) is None
    assert rag.retrieve(None, "x", 5, user_id="alice", community_id=None) == []


async def test_a_community_with_no_knowledge_base_yet_is_not_created_by_reading(
    memory_qdrant,
):
    """@verifies REQ-0022"""
    assert rag.build_retriever(5, user_id="alice", community_id="new-rec") is None
    assert kb_collections.aliases(memory_qdrant.client) == {}


async def test_writing_under_the_same_id_replaces_rather_than_duplicates(memory_qdrant):
    """An edited source page used to be indexed again beside its old version.

    @verifies REQ-0032
    """
    await put(COMMUNITY, "first version", "page", title="page", scope="system")
    await put(COMMUNITY, "second version", "page", title="page", scope="system")

    retriever = rag.build_retriever(10, user_id=None, community_id=COMMUNITY)
    nodes = rag.retrieve(retriever, "page", 10, user_id=None, community_id=COMMUNITY)
    assert [n.get_content() for n in nodes] == ["second version"]


async def test_a_deleted_document_is_gone_from_the_community(memory_qdrant):
    """@verifies REQ-0021"""
    await put(COMMUNITY, "Shared", "attachment:1", title="shared", scope="system")

    await rag.delete_document("attachment:1", community_id=COMMUNITY)

    assert titles(COMMUNITY, None) == set()


async def test_deleting_from_a_community_with_no_knowledge_base_is_a_no_op(memory_qdrant):
    """@verifies REQ-0021"""
    await rag.delete_document("attachment:1", community_id="new-rec")
    assert kb_collections.aliases(memory_qdrant.client) == {}


async def test_the_filter_itself_does_the_scoping_not_only_the_check_after_it(
    two_communities,
):
    """`retrieve` re-checks every node in process. This asks the retriever directly, so
    what is asserted is the filter Qdrant applied.

    @verifies REQ-0022
    """
    retriever = rag.build_retriever(20, user_id="alice", community_id=COMMUNITY)

    raw = {n.metadata["title"] for n in retriever.retrieve("anything")}

    assert raw == {"handbook", "guide", "alice-bill"}
