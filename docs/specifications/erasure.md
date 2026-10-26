# Erasure and retention

What the assistant holds about a member: their conversations (messages, with the trace of
each answer, REQ-0053), their own uploads (`user` scope: a database row with the
extracted text, a stored file, and the vectors indexed from it), all keyed by the `sub`
(REQ-0047). Conversations are never embedded: they live only in the database.

A `system` upload is what a manager shared with a community (REQ-0005, REQ-0017). It has
no owner and is not a member's personal data here; nothing in this file deletes one.

The operations below are the assistant's own. Which service asks for a person's erasure
across the platform is not decided here.

---

### REQ-0056 — deleting an attachment reaches every vector, or keeps what is needed to retry

An attachment's vectors are deleted by their payload `attachment_id` in **every
collection this service can have written**: each knowledge-base generation of every
community and every embedding model, whether an alias points at it or not (REQ-0041), and
the collection used before knowledge bases were per community. A row with no community
(written before then) is covered the same way.

The order is vectors, then the stored file, then the row. A failure at any step stops
the delete and is reported, and the row is left in place: the same delete can be run
again, and repeating a delete that already succeeded in part is harmless. No vector is
left without a row to find it by.

A process that cannot see the stored files — local storage whose directory does not
exist there, as in a pod without the service's volume — deletes nothing and reports the
attachment as not deleted, rather than take every file for already gone.

### REQ-0057 — a person can be erased by their `sub`

`celine-assistant erase-subject <sub>`, and `POST /admin/subjects/erase` with
`{"sub": "<sub>"}`, delete:

- every conversation of the person and every message in it, the trace included;
- every message stored under the person's id in any other conversation;
- every `user`-scope attachment the person owns, each through REQ-0056;
- every vector whose `owner_user_id` is the person, in every collection REQ-0056 names,
  except those marked `scope: system`.

The answer counts what was removed from each store: `conversations`, `messages`,
`attachments`, `files`, `vectors`, and lists in `failed` the attachments that could not
be deleted, and `vectors` when the final vector sweep could not run. It is idempotent: erasing a person already erased removes nothing and
succeeds. Shared material — `system` uploads and registered knowledge sources — is never
touched.

The route requires the scope **`assistant.subject.erase`** in the verified token's `scope`
claim; anything else is `403`, a platform administrator's token included unless it
carries that scope. The subject travels in the body, not in the path, so it does not
reach access logs; the service logs the caller and the counts, not the subject. A
partial failure answers `503` with the same report, and the CLI exits `1`.

### REQ-0058 — nothing of a member's is kept more than 12 months after it was last used

The period is `RETENTION_MONTHS`, 12 by default, as the published privacy notice
promises. `celine-assistant retention run` deletes:

- each conversation whose newest message is older than the period (a conversation with
  no message: its creation), with its messages;
- each `user`-scope attachment not used within the period, through REQ-0056. It is
  *used* when an answer to its owner lists it in its trace (REQ-0053) — as an attachment
  given to the turn, or as the `attachment_id` of a retrieved source; otherwise its last
  use is its upload.

The cut-off is the same calendar date that many months back. `--dry-run` counts what
would go and deletes nothing; `--months N` overrides the setting for one run. The answer
gives the cut-off and the counts, and the attachments that could not be deleted, in
which case the command exits `1`. `system` attachments are not subject to it.

### REQ-0059 — vectors left without an attachment are found, and removed on request

`celine-assistant kb orphans` lists, per collection REQ-0056 names, each indexed
`attachment_id` that has no attachment row, and how many vectors carry it.
`--delete` deletes them. A vector is written only after its row (REQ-0021), so an upload
in progress is never one.

---

## Known limits

**A use is known only from the trace.** Uses before REQ-0053 was deployed were not
recorded, so an older upload counts as unused since its upload until an answer lists it.

**Rows stored under a login session id** before identity became the `sub` (REQ-0047) are
not found by REQ-0057.
