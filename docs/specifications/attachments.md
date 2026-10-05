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

### REQ-0048 — an upload is one of a fixed list of types, decided from its bytes

The type is decided by the file's own content, never by what the client declared, and
the decided type is what is stored and served:

| Type | Recognised by |
|---|---|
| PDF | `%PDF` magic |
| PNG, JPEG, GIF, WebP images | their magic bytes |
| Word, Excel, PowerPoint (`.docx`, `.xlsx`, `.pptx`) | a zip holding `[Content_Types].xml` and that format's parts, under its extension |
| plain text, Markdown, CSV (`.txt`, `.md`, `.csv`) | UTF-8 with no NUL byte, under its extension |

Anything else — HTML, SVG, XML, scripts, archives, executables, a name whose bytes are
something else — is answered `415` before it is stored or indexed. The list is the
same for `POST /upload` and `POST /admin/uploads`.

### REQ-0049 — a stored file is served so that no browser runs it

`GET /attachments/{id}/raw` serves the stored type when it is on the REQ-0048 list and
`application/octet-stream` otherwise (rows written before the list existed carry the
type the client declared). Every response carries `X-Content-Type-Options: nosniff` and
`Cache-Control: private, no-store`.

- **An image or a PDF is `inline`**; everything else is `Content-Disposition: attachment`.
- **The content policy is `default-src 'none'` with `sandbox`**, so a file opened
  directly runs no script and has no access to this origin. A PDF has
  `default-src 'none'; object-src 'self'` without `sandbox`, because browsers' built-in
  PDF viewers do not render under it; its type is still only ever a real PDF (REQ-0048).
- The file name is given ASCII-only in `filename`, with the full sanitised name
  (REQ-0015) in `filename*` (RFC 6266) when they differ.

### REQ-0016 — a user-scoped attachment is reachable only by its owner or a platform administrator

Reading it, downloading it, deleting it and attaching it to a chat turn all enforce this.
The tool the model calls answers "not found" rather than "forbidden", because the model
relays tool output to the user.

### REQ-0017 — a system-scoped attachment is readable by the members of its community

That is what the scope is for: a manager shared it with their REC (REQ-0005). A member of
another community, or a caller with none, is refused — by the tool the model calls, as
"not found". A platform administrator (REQ-0004) reads any.

### REQ-0018 — a system-scoped attachment is deletable only by a manager of its community or a platform administrator

### REQ-0019 — a listing returns the caller's own attachments and their community's system ones

### REQ-0020 — an unknown attachment is not found

Reading or deleting one is `404`. Naming one in a chat request is ignored, so that a
client holding a stale id does not lose the turn.

### REQ-0021 — an upload is text-extracted where possible, and indexed when there is text

Images are captioned by the vision model; PDFs are text-extracted and fall back to
rendering pages for the vision model; everything else goes through MarkItDown. The type
is the one decided at upload (REQ-0048). Extraction that yields text is indexed and reported as `indexed`; extraction
that yields nothing, or fails, leaves the file stored and reported as `stored`.

An upload is recorded with the caller's community (REQ-0040) and indexed into that
community's knowledge base; with no community it is stored and reported as `stored`.
An indexed upload is written under a document id derived from its attachment id, and
**deleting the attachment deletes the row, the blob and the indexed document**. Content
left retrievable has not been deleted; a storage or vector-store failure is logged and
does not strand the row.


