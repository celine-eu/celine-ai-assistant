# Skills and the tool loop

A **skill** is a group of tools the model may call. The set offered is rebuilt for every
request from the caller's own token — see ADR-0005.

---

### REQ-0025 — a tool call is routed to the skill that declares it

The first registered skill whose declared tools include the name handles it. A name no
skill declares, or arguments that will not parse, produce a structured JSON error rather
than an exception: the model chose the name, and it has to be able to read the answer and
recover.

### REQ-0026 — every tool is offered to the model in strict form

`strict: true`, `additionalProperties: false`, and **every declared property required**.
A skill's own `required` list is overwritten rather than merged, so a skill cannot
express an optional parameter — each `execute` must tolerate any declared argument being
supplied.

### REQ-0027 — a skill is offered only when it can actually work

The documents skill is always available. Each upstream skill needs both its configured
URL and a forwarded caller token; without either it is silently absent and its absence is
logged. Weather is served by the digital twin, so it needs that URL; flexibility needs
both its own and the twin's.

### REQ-0028 — a skill failure is a tool result, never an exception

By the time a tool runs the response is already streaming, so raising would truncate the
answer mid-sentence. Every skill catches, logs, and returns `{"error": "..."}`. Where an
upstream returns nothing, the skill says so in words rather than reporting zero — a zero
is a number, and the model will repeat it as one.

A figure reported as a member's own covers everything they own: participant metrics query
**every** registered meter and combine the readings, and self-consumption is the
per-interval overlap of production and consumption rather than the minimum of the
window's totals.

### REQ-0029 — starter prompts are filtered to the skills that are available

Suggestions and tool labels are served in the requested language, falling back to
English. A suggestion whose skill is not registered is not offered.

**At least one suggestion names the documents skill**, which needs no upstream and no
forwarded token — otherwise a deployment that passes identity headers and not the access
token opens with no prompts at all.

### REQ-0030 — what reaches the model is bounded, and a turn always ends in an answer

A tool result longer than `MAX_TOOL_RESULT_CHARS` is truncated — by dropping whole
entries when the payload is a JSON `results` list, so what arrives is still parseable,
and by cutting the string otherwise.

The tool loop runs at most `MAX_TOOL_ROUNDS` times, and **the last round is offered no
tools**, so a model that would otherwise keep calling them has to answer in prose. A turn
producing neither an answer nor an error event is not an outcome a client can render.


