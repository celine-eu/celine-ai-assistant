# Training materials

The curated corpus is a **git checkout of `celine-training-materials`**, indexed into the
vector collection. Its content shape is a dependency: what that repository publishes is
what this service can answer questions about.

---

### REQ-0031 — a Markdown document is indexed with a title and a public location

YAML front matter is stripped. The title is the first heading, or the filename stem when
there is none. The location mirrors the docs site's routing rather than the file layout:
`guide/index.md` publishes as `guide/`, `guide/solar.md` as `guide/solar/`. Every
document is indexed `hidden`, so it reaches the model and not the citation list. A
root-level `index.md` publishes as the site root, `/`.

### REQ-0032 — ingestion is incremental, keyed on content

A manifest records a hash of each document's text. A document whose hash is unchanged is
skipped; an edited one is re-indexed; a forced run ignores the manifest entirely. An
empty document is neither indexed nor counted. The manifest file is shared with the other
ingester, so a save merges rather than replaces.

### REQ-0033 — a sync refuses rather than discarding work

The sync is `git fetch` and `git checkout --detach`, which would silently discard a local
edit. It refuses when the checkout is dirty, when the configured path exists but is not a
checkout, and when there is nothing to clone from. A refusal is reported to the caller as
`409`. Startup tolerates all of it: a deployment with neither a checkout nor a URL boots
and says it skipped.


