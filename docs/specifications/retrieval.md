# Retrieval

Each community (REC) has a knowledge base of its own: its registered sources, what its
managers shared, and what its members uploaded. The assistant answers a member from
their community's, and from no other.

---

### REQ-0022 — retrieval is scoped to what the caller may read

Only the caller's community's knowledge base is searched (REQ-0040); a caller with no
community retrieves nothing, and reading never creates a knowledge base. Inside it, the
rule below is applied on **every** retrieval path — the chat route's, and the
`search_documents` tool the model can call for itself — and every term requires
`community_id` to be the caller's:

| May be retrieved | Rule |
|---|---|
| the community's source material | `kind` is `kb_source` |
| a document a manager shared | `scope` is `system` |
| the caller's own upload | `scope` is `user` **and** `owner_user_id` is the caller |

Anything else is withheld: the rule denies by default, so a document carrying metadata
this code did not write is not returned, and a point that landed in the wrong
community's collection is not returned either.

It is enforced twice — as a metadata filter inside the vector store, which is the real
mechanism, and again on each returned node in this process. `build_retriever` takes the
caller id and community as keyword arguments with no default, so omitting one is a
`TypeError` rather than an unfiltered query.

Separately, a chunk marked `hidden` is withheld from the `sources` event but still given
to the model: source material is context a reader cannot follow a citation to. **The
`hidden` flag is not an access control** and must never be used as one.

### REQ-0023 — an attached file leads the context

Files named in a chat request are authorised, summarised into a single context block —
filename, type, scope and description — and placed **first**, ahead of anything retrieval
found. The user attached it a second ago; it outranks a similarity score.

### REQ-0024 — a turn with attachments and no text is still a question

The route supplies one ("analyse the attached files…"). Retrieval is skipped when there
is no text to retrieve on.

### REQ-0041 — a knowledge base can be rebuilt, and an embedding model replaced, without a gap

A community's knowledge base is the Qdrant alias
`<QDRANT_COLLECTION>__<community_id>__<fingerprint>`, where the fingerprint hashes the
embedding model and vector size, pointing at a timestamped generation (ADR-0008). A
community id that is not already a valid name (lower case, digits, `-`, single `_`, at
most 64) is refused, never normalised.

`celine-assistant kb reindex` builds a new generation from the registered sources and
the community's attachment rows (re-embedding the stored text, or with `--re-extract`
running extraction again), checks every expected document reached it, and only then
moves the alias in one operation; a failed rebuild deletes its generation and leaves the
live one as it was. Attachments added or deleted during the build are reconciled after
the move. The previous generation is kept until `kb prune`.

Because the model is part of the alias, a new model's knowledge bases are built beside
the current ones (`--embed-model`), and the deploy that changes `LLM_EMBED_MODEL` is the
switch. The service refuses to start when a community has knowledge bases only for
another model.

---

## Known limits

Everything indexed before knowledge bases were per community sits in the single
`QDRANT_COLLECTION` collection, which nothing reads any more. `kb migrate-legacy`
rebuilds it into a community (REQ-0042); `kb prune --legacy` then deletes it.

What is actually in the collection is recorded in the companion's knowledge.
