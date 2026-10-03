# Knowledge sources

A community's reference material comes from **sources registered for it**: a git
repository (optionally one subdirectory of it, at a ref) or a directory. What used to be
the one training-materials repository, the same for everyone, is now one such source.
Sources are registered and synced with `celine-assistant kb` — see the README.

---

### REQ-0031 — a Markdown document is indexed with a title and a public location

YAML front matter is stripped. The title is the first heading, or the filename stem when
there is none. The location mirrors the docs site's routing rather than the file layout:
`guide/index.md` publishes as `guide/`, `guide/solar.md` as `guide/solar/`, a root-level
`index.md` as `/`. Every document is indexed `hidden`, so it reaches the model and not
the citation list. Files under a hidden directory (`.github/`, …) are not read.

### REQ-0032 — ingestion is incremental, keyed on content, and follows deletions

A hash of each document's text is recorded per source **and per collection**. A document
whose hash is unchanged is skipped; an edited one replaces what was indexed under its
document id (`source:<source id>:<path>`) rather than adding beside it; a document the
source no longer has is removed; a full run ignores what was recorded. An empty document
is neither indexed nor counted. Because the record is per collection, a rebuild's new
generation always starts from nothing.

### REQ-0033 — a sync refuses rather than discarding work

A git source is cloned into `KB_SOURCES_DIR/<source id>`, then `git fetch` and
`git checkout --detach <ref or origin/HEAD>`, which would silently discard a local edit.
It refuses when the clone is dirty and when its directory exists but is not a checkout;
a directory source refuses when the directory is missing, and a subdirectory may not
leave the source. One failing source does not stop the others: its error is in the
result, and `kb sync` exits non-zero. The settings that configured the old single
repository (`TRAINING_MATERIALS_*`, `MANIFEST_PATH`, `INGEST_*`) are read by nothing;
a leftover is logged at startup rather than refused.

### REQ-0042 — legacy data is migrated into one community by a command, never by default

`kb migrate-legacy --community <id>` gives every attachment that has no community the
one named, registers the training-materials repository (`--git`, or a leftover
`TRAINING_MATERIALS_REPO_URL`) as its git source unless already registered, and rebuilds
that community. Nothing assigns legacy data on its own, and the community is always an
argument: no community id is a default in this repository. The old collection is left
in place until `kb prune --legacy`.

### REQ-0043 — sources belong to one community, and removing one removes its documents

`kb source add` records the community, the kind, the location, and for git the ref and
subdirectory; an unknown kind, an invalid community id, both or neither of `--git` and
`--dir`, or a missing directory is refused. `kb source remove` deletes the source's
documents from the live knowledge base along with the registration.

### REQ-0044 — a private git source is cloned with a token that is stored nowhere

With `KB_GIT_TOKEN` set, git is given an `Authorization` header for
`KB_GIT_TOKEN_HOST` (default `github.com`) through its environment (`GIT_CONFIG_*`), for
each invocation only. The token is never part of a source's stored URL, git's argument
list, or the clone's `.git/config`. git never prompts for credentials; a failed clone or
fetch is a source error carrying git's own message.
