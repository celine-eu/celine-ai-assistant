# Retrieval

The assistant answers from a vector collection assembled from two sources: curated
training material, and whatever users upload.

---

### REQ-0022 — retrieval is scoped to what the caller may read

One shared collection holds three things, and the rule that keeps them apart is applied
on **every** retrieval path — the chat route's, and the `search_documents` tool the model
can call for itself:

| May be retrieved | Rule |
|---|---|
| the curated corpus | `kind` is `training_material` or `site_doc` |
| an administrator's shared upload | `scope` is `system` |
| the caller's own upload | `scope` is `user` **and** `owner_user_id` is the caller |

Anything else is withheld: the rule denies by default, so a document carrying metadata
this code did not write is not returned.

It is enforced twice — as a metadata filter inside the vector store, which is the real
mechanism, and again on each returned node in this process, which is the half a
serviceless test can prove. `build_retriever` takes the caller id as a keyword argument
with no default, so omitting it is a `TypeError` rather than an unfiltered query.

Separately, a chunk marked `hidden` is withheld from the `sources` event but still given
to the model: training material is context a reader cannot follow a citation to. **The
`hidden` flag is not an access control** and must never be used as one.

### REQ-0023 — an attached file leads the context

Files named in a chat request are authorised, summarised into a single context block —
filename, type, scope and description — and placed **first**, ahead of anything retrieval
found. The user attached it a second ago; it outranks a similarity score.

### REQ-0024 — a turn with attachments and no text is still a question

The route supplies one ("analyse the attached files…"). Retrieval is skipped when there
is no text to retrieve on.

---

## Known limits

**Documents indexed before 2026-08-15 carry generated document ids**, so REQ-0021's
deletion does not reach them. They are still scoped correctly for retrieval — the
metadata the rule reads is metadata they already carry. Clearing them needs a reindex.

What is actually in the collection is recorded in the companion's knowledge.
