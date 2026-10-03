"""Where each community's knowledge base lives in Qdrant, and how it is replaced.

```text
alias        <prefix>__<community_id>__<fingerprint>                 what the service reads and writes
collection   <prefix>__<community_id>__<fingerprint>__<timestamp>    one generation, never renamed
```

`<fingerprint>` hashes the embedding model and its vector size. Old and new model read
different aliases, so a new model's knowledge bases can be built while the service still
serves the old ones, and the deploy that changes `LLM_EMBED_MODEL` is the switch. A
rebuild on the same model builds a new generation and moves the alias to it in one
operation. See ADR-0008.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from . import llm
from .settings import settings

log = logging.getLogger(__name__)

SEP = "__"

# Lower case, digits, `-` and single `_`: a Qdrant name, and `__` stays a separator.
_COMMUNITY_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]|_(?!_))*$")
_FINGERPRINT_LEN = 10
_STAMP_FORMAT = "%Y%m%d%H%M%S"

_dimensions_cache: dict[str, int] = {}


class InvalidCommunityId(ValueError):
    pass


@dataclass(frozen=True)
class KbName:
    community_id: str
    fingerprint: str
    generation: str | None  # None for an alias

    @property
    def alias(self) -> str:
        return alias_name(self.community_id, self.fingerprint)


def validate_community_id(community_id: str) -> str:
    """The id unchanged, or refused.

    Never normalised: two communities that normalise to one name would share a
    knowledge base.
    """
    if (
        not isinstance(community_id, str)
        or len(community_id) > 64
        or not _COMMUNITY_RE.match(community_id)
    ):
        raise InvalidCommunityId(
            f"community id {community_id!r} cannot name a knowledge base: use lower "
            "case letters, digits, '-' and single '_'"
        )
    return community_id


def embedding_dimensions() -> int:
    """The configured vector size, probing the model once when none is set."""
    if settings.llm_embed_dimensions:
        return settings.llm_embed_dimensions
    model = settings.llm_embed_model
    if model not in _dimensions_cache:
        _dimensions_cache[model] = llm.embedding_dimensions()
    return _dimensions_cache[model]


def fingerprint(model: str | None = None, dimensions: int | None = None) -> str:
    model = model if model is not None else settings.llm_embed_model
    dimensions = dimensions if dimensions is not None else embedding_dimensions()
    digest = hashlib.sha256(f"{model}\n{dimensions}".encode("utf-8")).hexdigest()
    return digest[:_FINGERPRINT_LEN]


def alias_name(community_id: str, fp: str | None = None) -> str:
    validate_community_id(community_id)
    return SEP.join([settings.qdrant_collection, community_id, fp or fingerprint()])


def generation_name(alias: str, now: float | None = None) -> str:
    stamp = time.strftime(_STAMP_FORMAT, time.gmtime(now if now is not None else time.time()))
    return f"{alias}{SEP}{stamp}"


def parse_name(name: str) -> KbName | None:
    """What a Qdrant name says, or None for a name this module did not make."""
    prefix = settings.qdrant_collection + SEP
    if not name.startswith(prefix):
        return None
    parts = name[len(prefix):].split(SEP)
    if len(parts) not in (2, 3):
        return None
    community_id, fp = parts[0], parts[1]
    if not _COMMUNITY_RE.match(community_id) or len(fp) != _FINGERPRINT_LEN:
        return None
    return KbName(community_id, fp, parts[2] if len(parts) == 3 else None)


def qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30)


def aliases(client: QdrantClient) -> dict[str, str]:
    """Every knowledge-base alias, to the collection it points at."""
    return {
        a.alias_name: a.collection_name
        for a in client.get_aliases().aliases
        if parse_name(a.alias_name) is not None
    }


def generations(client: QdrantClient) -> list[str]:
    """Every knowledge-base collection, aliased or not."""
    return sorted(
        c.name
        for c in client.get_collections().collections
        if (parsed := parse_name(c.name)) is not None and parsed.generation
    )


def vector_size(client: QdrantClient, name: str) -> int | None:
    return getattr(client.get_collection(name).config.params.vectors, "size", None)


def create_generation(
    client: QdrantClient, community_id: str, *, dimensions: int | None = None
) -> str:
    dimensions = dimensions or embedding_dimensions()
    name = generation_name(alias_name(community_id))
    # Two rebuilds in one second would otherwise collide.
    while client.collection_exists(name):
        time.sleep(1)
        name = generation_name(alias_name(community_id))
    client.create_collection(
        collection_name=name,
        vectors_config=qm.VectorParams(size=dimensions, distance=qm.Distance.COSINE),
    )
    log.info("kb_generation_created", extra={"collection": name})
    return name


def point_alias(client: QdrantClient, alias: str, collection: str) -> str | None:
    """Point `alias` at `collection` in one operation; the collection it left, if any."""
    previous = aliases(client).get(alias)
    operations: list = []
    if previous:
        operations.append(
            qm.DeleteAliasOperation(delete_alias=qm.DeleteAlias(alias_name=alias))
        )
    operations.append(
        qm.CreateAliasOperation(
            create_alias=qm.CreateAlias(collection_name=collection, alias_name=alias)
        )
    )
    client.update_collection_aliases(change_aliases_operations=operations)
    log.info(
        "kb_alias_moved",
        extra={"alias": alias, "collection": collection, "previous": previous},
    )
    return previous


def ensure_alias(client: QdrantClient, community_id: str) -> str:
    """The community's alias for the configured model, created on first write."""
    alias = alias_name(community_id)
    if alias in aliases(client):
        return alias
    collection = create_generation(client, community_id)
    try:
        point_alias(client, alias, collection)
    except Exception:
        # Another writer won the race; use theirs and drop ours.
        if alias not in aliases(client):
            raise
        client.delete_collection(collection)
    return alias


def check_startup(client: QdrantClient) -> None:
    """Refuse to serve when the embedding model changed and nothing was rebuilt for it.

    A community with knowledge bases only for another model would answer every
    question from nothing, and a new upload would start an empty one beside the old.
    """
    current = fingerprint()
    by_community: dict[str, set[str]] = {}
    for alias in aliases(client):
        parsed = parse_name(alias)
        if parsed:
            by_community.setdefault(parsed.community_id, set()).add(parsed.fingerprint)

    stale = sorted(c for c, fps in by_community.items() if current not in fps)
    if stale:
        raise RuntimeError(
            f"the embedding model changed ({settings.llm_embed_model!r}) and no knowledge "
            f"base was built for it for: {', '.join(stale)}. Run "
            "`celine-assistant kb reindex --all` with the new model first."
        )
