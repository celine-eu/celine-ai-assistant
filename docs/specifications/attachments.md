# Attachments

An attachment has a **scope**: `user`, owned by the person who uploaded it, or `system`,
uploaded by an administrator and shared with everyone.

---

### REQ-0014 — an upload larger than the configured limit is refused

`MAX_UPLOAD_MB` bounds it, and the response is `413` naming the limit. The limit never
falls below one megabyte, whatever it is configured to.

The body is read in chunks and abandoned once the limit is passed, so the limit bounds
what the process allocates and not merely what it stores.

### REQ-0015 — a stored file is filed under its owner with a sanitised name

The blob path is `<owner or _system>/<timestamp>/<random id>_<sanitised filename>`. The
sanitiser reduces the name to a basename and drops anything outside
`[alphanumeric] _ - . +`, capped at 200 characters; a name left with nothing becomes
`file`. The random id is what keeps two uploads of the same name apart.

**The owner id is sanitised too.** It is caller-controlled — a JWT claim, or with
`OAUTH2_TRUST_HEADERS` on, a request header — so separators are stripped rather than
honoured, `@` and `.` are kept because an id is usually an email, and an id that reduces
to nothing usable is refused rather than coerced.

### REQ-0016 — a user-scoped attachment is reachable only by its owner or an administrator

Reading it, downloading it, deleting it and attaching it to a chat turn all enforce this.
The tool the model calls answers "not found" rather than "forbidden", because the model
relays tool output to the user.

### REQ-0017 — a system-scoped attachment is readable by any identified caller

That is what the scope is for.

### REQ-0018 — a system-scoped attachment is deletable only by an administrator

### REQ-0019 — a listing returns the caller's own attachments and every system one

### REQ-0020 — an unknown attachment is not found

Reading or deleting one is `404`. Naming one in a chat request is ignored, so that a
client holding a stale id does not lose the turn.

### REQ-0021 — an upload is text-extracted where possible, and indexed when there is text

Images are captioned by the vision model; PDFs are text-extracted and fall back to
rendering pages for the vision model; everything else goes through MarkItDown. The type
is decided by the file's own magic bytes, and only falls back to what the client
declared. Extraction that yields text is indexed and reported as `indexed`; extraction
that yields nothing, or fails, leaves the file stored and reported as `stored`.

An indexed upload is written under a document id derived from its attachment id, and
**deleting the attachment deletes the row, the blob and the indexed document**. Content
left retrievable has not been deleted; a storage or vector-store failure is logged and
does not strand the row.


