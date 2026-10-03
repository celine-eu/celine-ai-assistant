"""Shared fixtures.

The whole point of this file is that **no test reaches a real service**. This
repository talks to five things it does not own — Qdrant, an OpenAI-compatible LLM,
PostgreSQL, and three platform APIs through `celine-sdk` — and every one of them is
faked here, at the narrowest boundary that still exercises our code.

The environment is set *before* `celine.assistant` is imported anywhere. `settings.py`
builds its `Settings()` at import time and `db/engine.py` builds the async engine from
it, so by the time a test module is collected the wiring has already happened and
cannot be overridden with a fixture. See `.agents/knowledge/import-time-wiring.md`.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Must run before the first `celine.assistant` import. Do not move below them.
# ---------------------------------------------------------------------------
os.environ.setdefault("APP_ENV", "test")
# The suite runs on development values (header trust, a test database password, no
# Qdrant key) that the posture guard refuses anywhere but dev. CELINE_ENV wins over
# APP_ENV. Hardened behaviour is tested with the environment passed in
# (`tests/unit/test_posture.py`).
os.environ.setdefault("CELINE_ENV", "dev")
os.environ["LLM_BASE_URL"] = "http://127.0.0.1:1/v1"
os.environ["LLM_CHAT_MODEL"] = "test-chat"
os.environ["LLM_EMBED_MODEL"] = "test-embed"
os.environ["LLM_EMBED_DIMENSIONS"] = "8"
for _removed in ("OPENAI_API_KEY", "OPENAI_CHAT_MODEL", "OPENAI_EMBED_MODEL", "OPENAI_VISION_MODEL"):
    os.environ.pop(_removed, None)
# Parsed by SQLAlchemy at import; never connected to, because HistoryStore is faked.
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@127.0.0.1:1/test"
os.environ["QDRANT_URL"] = "http://127.0.0.1:1"
os.environ["OAUTH2_TRUST_HEADERS"] = "true"
os.environ["OAUTH2_JWKS_URL"] = ""
os.environ["OAUTH2_ISSUER"] = ""
os.environ["ADMIN_GROUP"] = "admins"
for _removed in ("TRAINING_MATERIALS_REPO_URL", "TRAINING_MATERIALS_PATH", "INGEST_ENABLE"):
    os.environ.pop(_removed, None)
os.environ["KB_SYNC_ON_START"] = "false"

import time  # noqa: E402
import uuid  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from celine.assistant import auth as auth_module  # noqa: E402
from celine.assistant.history import get_history_store  # noqa: E402
from celine.assistant.main import create_app  # noqa: E402
from celine.assistant.settings import settings  # noqa: E402
from celine.assistant import rag as _rag  # noqa: E402

_REAL_GET_INDEX = _rag._get_index

USER_ID = "alice"
OTHER_USER_ID = "bob"
ADMIN_ID = "root"


# ---------------------------------------------------------------------------
# History store double
# ---------------------------------------------------------------------------


class _Conv:
    def __init__(self, conversation_id: str, user_id: str, created_at: int) -> None:
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.created_at = created_at


class FakeHistoryStore:
    """In-memory stand-in for `HistoryStore`.

    Its method signatures are asserted against the real class in
    `tests/unit/test_history_contract.py`, so a change to the store that this fake
    does not follow fails a test rather than silently making the API suite fictional.
    """

    def __init__(self) -> None:
        self.conversations: dict[str, _Conv] = {}
        self.messages: list[dict[str, Any]] = []
        self.attachments: dict[str, dict[str, Any]] = {}

    # -- conversations --

    async def get_or_create_conversation(
        self, user_id: str, conversation_id: str | None = None
    ) -> _Conv:
        if conversation_id:
            existing = self.conversations.get(conversation_id)
            if existing and existing.user_id == user_id:
                return existing
        conv = _Conv(conversation_id or str(uuid.uuid4()), user_id, int(time.time()))
        self.conversations[conv.conversation_id] = conv
        return conv

    async def list_conversations(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        rows = []
        for conv in self.conversations.values():
            if conv.user_id != user_id:
                continue
            msgs = [m for m in self.messages if m["conversation_id"] == conv.conversation_id]
            rows.append(
                {
                    "conversation_id": conv.conversation_id,
                    "created_at": conv.created_at,
                    "last_message_at": max((m["created_at"] for m in msgs), default=None),
                    "message_count": len(msgs),
                    "last_snippet": (msgs[-1]["content"] if msgs else "")[:120],
                }
            )
        rows.sort(key=lambda r: r["last_message_at"] or 0, reverse=True)
        return rows[offset : offset + limit]

    async def conversation_exists(self, user_id: str, conversation_id: str) -> bool:
        conv = self.conversations.get(conversation_id)
        return conv is not None and conv.user_id == user_id

    async def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        conv = self.conversations.get(conversation_id)
        if not conv or conv.user_id != user_id:
            return False
        del self.conversations[conversation_id]
        self.messages = [
            m for m in self.messages if m["conversation_id"] != conversation_id
        ]
        return True

    # -- messages --

    async def append_message(
        self, user_id: str, conversation_id: str, role: str, content: str
    ) -> str:
        msg_id = str(uuid.uuid4())
        self.messages.append(
            {
                "id": msg_id,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "role": role,
                "content": content,
                "created_at": len(self.messages),  # monotonic, unlike time()
            }
        )
        return msg_id

    async def list_messages(
        self, user_id: str, conversation_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        rows = [
            {k: m[k] for k in ("id", "conversation_id", "role", "content", "created_at")}
            for m in self.messages
            if m["conversation_id"] == conversation_id and m["user_id"] == user_id
        ]
        return rows[:limit]

    # -- attachments --

    async def record_attachment(
        self,
        *,
        scope: str,
        owner_user_id: str | None,
        community_id: str | None,
        uri: str,
        path: str,
        filename: str,
        content_type: str | None,
        size_bytes: int,
        caption: str | None = None,
        ocr_text: str | None = None,
    ) -> str:
        att_id = str(uuid.uuid4())
        self.attachments[att_id] = {
            "id": att_id,
            "scope": scope,
            "owner_user_id": owner_user_id,
            "community_id": community_id,
            "uri": uri,
            "path": path,
            "filename": filename,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "caption": caption,
            "ocr_text": ocr_text,
            "created_at": int(time.time()),
        }
        return att_id

    async def list_attachments_for_user(
        self, user_id: str, community_id: str | None, limit: int = 200
    ) -> list[dict[str, Any]]:
        rows = [
            a
            for a in self.attachments.values()
            if (a["scope"] == "user" and a["owner_user_id"] == user_id)
            or (
                community_id
                and a["scope"] == "system"
                and a["community_id"] == community_id
            )
        ]
        rows.sort(key=lambda a: a["created_at"], reverse=True)
        return rows[:limit]

    async def list_attachments_for_community(
        self, community_id: str
    ) -> list[dict[str, Any]]:
        rows = [a for a in self.attachments.values() if a["community_id"] == community_id]
        rows.sort(key=lambda a: a["created_at"])
        return rows

    async def update_attachment_text(
        self, attachment_id: str, *, ocr_text: str | None, caption: str | None
    ) -> None:
        if attachment_id in self.attachments:
            self.attachments[attachment_id].update(ocr_text=ocr_text, caption=caption)

    async def attachment_communities(self) -> list[str]:
        return sorted(
            {a["community_id"] for a in self.attachments.values() if a["community_id"]}
        )

    async def count_attachments_without_community(self) -> int:
        return sum(1 for a in self.attachments.values() if not a["community_id"])

    async def assign_community_to_unassigned(self, community_id: str) -> int:
        n = 0
        for a in self.attachments.values():
            if not a["community_id"]:
                a["community_id"] = community_id
                n += 1
        return n

    async def get_attachment_any(self, attachment_id: str) -> dict[str, Any] | None:
        return self.attachments.get(attachment_id)

    async def delete_attachment_any(self, attachment_id: str) -> dict[str, Any] | None:
        return self.attachments.pop(attachment_id, None)


class FakeKbStore:
    """In-memory stand-in for `KbStore`; its surface is checked against the real one in
    `tests/unit/test_history_contract.py`, its SQL in `tests/db/test_kb_store.py`."""

    def __init__(self) -> None:
        self.sources: dict[str, dict[str, Any]] = {}
        self.versions: dict[tuple[str, str], dict[str, str]] = {}

    async def add_source(
        self,
        *,
        community_id: str,
        kind: str,
        location: str,
        ref: str | None = None,
        subpath: str | None = None,
    ) -> dict[str, Any]:
        src = {
            "id": str(uuid.uuid4()),
            "community_id": community_id,
            "kind": kind,
            "location": location,
            "ref": ref,
            "subpath": subpath or None,
            "last_synced_version": None,
            "last_synced_at": None,
            "created_at": int(time.time()),
        }
        self.sources[src["id"]] = src
        return dict(src)

    async def list_sources(self, community_id: str | None = None) -> list[dict[str, Any]]:
        return [
            dict(s)
            for s in self.sources.values()
            if not community_id or s["community_id"] == community_id
        ]

    async def get_source(self, source_id: str) -> dict[str, Any] | None:
        src = self.sources.get(source_id)
        return dict(src) if src else None

    async def remove_source(self, source_id: str) -> dict[str, Any] | None:
        for key in [k for k in self.versions if k[0] == source_id]:
            del self.versions[key]
        return self.sources.pop(source_id, None)

    async def mark_synced(self, source_id: str, version: str | None) -> None:
        if source_id in self.sources:
            self.sources[source_id].update(
                last_synced_version=version, last_synced_at=int(time.time())
            )

    async def document_versions(self, source_id: str, collection: str) -> dict[str, str]:
        return dict(self.versions.get((source_id, collection), {}))

    async def set_document_versions(
        self, source_id: str, collection: str, versions: dict[str, str]
    ) -> None:
        self.versions[(source_id, collection)] = dict(versions)

    async def forget_collection(self, collection: str) -> None:
        for key in [k for k in self.versions if k[1] == collection]:
            del self.versions[key]

    async def source_communities(self) -> list[str]:
        return sorted({s["community_id"] for s in self.sources.values()})


# ---------------------------------------------------------------------------
# App fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_vector_store(monkeypatch):
    """Nothing may reach a real Qdrant.

    `rag.qdrant()` is the one place a client is built. A path that reaches it without
    a test saying so — the vector-store delete on the attachment path once did —
    would otherwise open sockets to a closed port and swallow the failure.

    Failing loudly is what keeps ADR-0001 true: a test that needs the index either
    fakes the function it calls, or asks for `memory_qdrant`.
    """
    import celine.assistant.rag as rag_mod

    def _refuse(*args, **kwargs):
        raise AssertionError(
            "a test reached Qdrant; fake the rag function you are exercising, or use "
            "the memory_qdrant fixture"
        )

    monkeypatch.setattr(rag_mod, "qdrant", _refuse)
    monkeypatch.setattr(rag_mod, "_get_index", _refuse)
    rag_mod.reset_indexes()


class MemoryQdrant:
    def __init__(self, client) -> None:
        self.client = client


@pytest.fixture
def memory_qdrant(monkeypatch) -> MemoryQdrant:
    """A real Qdrant engine, in process: `qdrant-client`'s local mode.

    It runs the payload filters and the alias operations themselves, so retrieval
    scoping and rebuilds are exercised rather than faked. Embeddings are LlamaIndex's
    `MockEmbedding` at the configured size — every vector the same, so these tests
    say what is *allowed* back, never what ranks first.
    """
    from llama_index.core.embeddings import MockEmbedding
    from qdrant_client import QdrantClient

    import celine.assistant.kb_collections as kb_mod
    import celine.assistant.llm as llm_mod
    import celine.assistant.rag as rag_mod

    client = QdrantClient(":memory:")
    monkeypatch.setattr(rag_mod, "qdrant", lambda: client)
    monkeypatch.setattr(kb_mod, "qdrant_client", lambda: client)
    monkeypatch.setattr(rag_mod, "_get_index", _REAL_GET_INDEX)
    monkeypatch.setattr(
        llm_mod, "embed_model", lambda: MockEmbedding(embed_dim=settings.llm_embed_dimensions)
    )
    rag_mod.reset_indexes()
    yield MemoryQdrant(client)
    rag_mod.reset_indexes()


@pytest.fixture
def history() -> FakeHistoryStore:
    return FakeHistoryStore()


@pytest.fixture
def app(history: FakeHistoryStore):
    """The real app, with the history store overridden.

    The lifespan calls `kb_collections.check_startup()`, which connects to Qdrant; httpx's
    `ASGITransport` never emits lifespan events, which is what keeps that from running.
    Nothing therefore sets `app.state.history_store`, so the store is supplied the way
    `../dataset-api` supplies its sessions — by overriding the dependency.
    """
    application = create_app()
    application.dependency_overrides[get_history_store] = lambda: history
    return application


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
def user_headers() -> dict[str, str]:
    return {
        "x-auth-request-user": USER_ID,
        "x-auth-request-email": "alice@example.test",
        "x-auth-request-groups": "members",
    }


@pytest.fixture
def other_user_headers() -> dict[str, str]:
    return {
        "x-auth-request-user": OTHER_USER_ID,
        "x-auth-request-groups": "members",
    }


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {
        "x-auth-request-user": ADMIN_ID,
        "x-auth-request-groups": f"members,{settings.admin_group}",
    }


VALID_TOKEN = "a-token-that-verifies"

# Two RECs. A member's community is the alias of the REC organization in their token.
COMMUNITY = "example-rec"
OTHER_COMMUNITY = "other-rec"
NEIGHBOUR_ID = "bob-member"
MANAGER_ID = "carol"
OUTSIDER_ID = "dave"


class TokenIssuer:
    """Access tokens that verify, each carrying the claims it was issued with.

    Signing a real JWT and serving a JWKS would be testing `python-jose` and `httpx`;
    the crypto and the network are faked instead, and what remains under test is what
    this repository does with the claims — which is where the community comes from.
    """

    def __init__(self) -> None:
        self.claims: dict[str, dict[str, Any]] = {}

    def issue(
        self,
        user_id: str,
        *,
        groups: tuple[str, ...] = ("members",),
        community: str | None = None,
        org_groups: tuple[str, ...] = (),
        organizations: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> dict[str, str]:
        claims: dict[str, Any] = {
            "sub": user_id,
            "email": f"{user_id}@example.test",
            "name": user_id,
            "groups": list(groups),
        }
        if organizations is None and community:
            organizations = {
                community: {"type": ["rec"], "groups": [f"/{g}" for g in org_groups]}
            }
        if organizations is not None:
            claims["organization"] = organizations
        token = token or f"token-for-{user_id}"
        self.claims[token] = claims
        return {"x-auth-request-access-token": token}


@pytest.fixture
def tokens(monkeypatch) -> TokenIssuer:
    issuer = TokenIssuer()

    async def _jwks_url_from_token(token: str) -> str:
        return "https://issuer.test/jwks"

    async def _get_jwks(url: str) -> dict:
        return {"keys": []}

    def _verify_jwt(token: str, jwks: dict) -> dict:
        if token not in issuer.claims:
            raise auth_module.AuthError("signature does not verify")
        return dict(issuer.claims[token])

    monkeypatch.setattr(auth_module, "_jwks_url_from_token", _jwks_url_from_token)
    monkeypatch.setattr(auth_module, "_get_jwks", _get_jwks)
    monkeypatch.setattr(auth_module, "_verify_jwt", _verify_jwt)
    return issuer


@pytest.fixture
def forwarded_token(tokens):
    """Headers carrying an access token that verifies.

    A token is what unlocks the upstream skills, and since a token that fails
    verification is refused outright (never downgraded to the headers), a test that
    wants those skills needs one that passes.
    """

    def _headers(user_id: str = USER_ID, groups: tuple[str, ...] = ("members",)):
        return tokens.issue(user_id, groups=groups, token=VALID_TOKEN)

    return _headers


@pytest.fixture
def member_headers(tokens) -> dict[str, str]:
    """Alice, a member of `COMMUNITY`."""
    return tokens.issue(USER_ID, community=COMMUNITY)


@pytest.fixture
def neighbour_headers(tokens) -> dict[str, str]:
    """Another member of the same REC."""
    return tokens.issue(NEIGHBOUR_ID, community=COMMUNITY)


@pytest.fixture
def manager_headers(tokens) -> dict[str, str]:
    """A manager of `COMMUNITY`, by a group inside its organization."""
    return tokens.issue(MANAGER_ID, community=COMMUNITY, org_groups=("managers",))


@pytest.fixture
def outsider_headers(tokens) -> dict[str, str]:
    """A member of another REC."""
    return tokens.issue(OUTSIDER_ID, community=OTHER_COMMUNITY)


# ---------------------------------------------------------------------------
# Retrieval double
# ---------------------------------------------------------------------------


class FakeNode:
    """Shaped like a LlamaIndex `NodeWithScore` as `rag.node_to_source` reads one."""

    def __init__(self, text: str, metadata: dict[str, Any], score: float = 0.5) -> None:
        self._text = text
        self.metadata = metadata
        self.score = score

    def get_content(self) -> str:
        return self._text


# Nodes shaped like the three things the collection actually holds. Which one a test
# reaches for decides whether `rag.is_visible_to` lets it through, so the choice is part
# of what the test says.


def curated_node(
    text: str, *, title: str = "Guide", community_id: str = COMMUNITY, **meta
) -> FakeNode:
    """A community's source material: readable by its members, cited to nobody."""
    return FakeNode(
        text,
        {
            "kind": "kb_source",
            "hidden": True,
            "title": title,
            "community_id": community_id,
            **meta,
        },
    )


def system_node(
    text: str, *, title: str = "Shared", community_id: str = COMMUNITY, **meta
) -> FakeNode:
    """A document a manager shared with the community."""
    return FakeNode(
        text,
        {
            "scope": "system",
            "kind": "document_content",
            "title": title,
            "community_id": community_id,
            **meta,
        },
    )


def user_node(
    text: str,
    owner: str,
    *,
    title: str = "Upload",
    community_id: str = COMMUNITY,
    **meta,
) -> FakeNode:
    """One member's own upload."""
    return FakeNode(
        text,
        {
            "scope": "user",
            "owner_user_id": owner,
            "kind": "document_content",
            "title": title,
            "community_id": community_id,
            **meta,
        },
    )


@pytest.fixture
def fake_retrieval(monkeypatch):
    """Replace Qdrant retrieval with a list you control.

    Patches `celine.assistant.routes` and `celine.assistant.skills.documents`
    separately: both import from `rag`, and the documents skill imports *inside* the
    function body, so it resolves `celine.assistant.rag` at call time rather than the
    name bound in `routes`.

    **The real `rag.is_visible_to` is applied to whatever you set**, so the scoping rule
    is exercised rather than faked away — a test that hands this fixture another
    member's document gets it filtered out, which is the point. `.calls` records the
    `user_id` and `community_id` each call was made with.
    """
    nodes: list[FakeNode] = []
    calls: list[dict] = []

    def _set(new_nodes: list[FakeNode]) -> None:
        nodes.clear()
        nodes.extend(new_nodes)

    def _build_retriever(top_k: int = 5, *, user_id: str | None, community_id: str | None):
        calls.append(
            {
                "where": "build_retriever",
                "top_k": top_k,
                "user_id": user_id,
                "community_id": community_id,
            }
        )
        return object()

    def _retrieve(retriever, query, top_k, *, user_id: str | None, community_id: str | None):
        calls.append(
            {
                "where": "retrieve",
                "query": query,
                "user_id": user_id,
                "community_id": community_id,
            }
        )
        return [
            n
            for n in nodes[:top_k]
            if rag_mod.is_visible_to(n.metadata, user_id, community_id)
        ]

    import celine.assistant.rag as rag_mod
    import celine.assistant.routes as routes_mod

    monkeypatch.setattr(routes_mod, "build_retriever", _build_retriever)
    monkeypatch.setattr(routes_mod, "retrieve", _retrieve)
    monkeypatch.setattr(rag_mod, "build_retriever", _build_retriever)
    monkeypatch.setattr(rag_mod, "retrieve", _retrieve)

    _set([])
    _set.calls = calls
    return _set
