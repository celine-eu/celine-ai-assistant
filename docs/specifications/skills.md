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
**every** registered meter and combine the readings. The meter rows hold the grid exchange
under production and consumption names (`production_kwh` is the export, `consumption_kwh`
the import); production is the export plus what was self-consumed, and consumption the
import plus what was self-consumed. A meter without a production meter (M2) reports only
the grid exchange and says that production and self-consumption are not measured — never
the export as production.

Points, level and ranking are the current season's: lifetime totals are not disclosed.

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

### REQ-0051 — what the model generates is bounded, and a cut answer says so

Every model call (each tool-loop round, the history summary, an image caption) carries
`max_tokens` = `LLM_MAX_TOKENS`, a positive integer that cannot be switched off. A
thinking model counts its reasoning against it.

A round that stops because it reached the cap (`finish_reason=length`) ends the turn with
an `error` event after whatever text it streamed, and runs none of the tool calls it was
writing: a truncated answer is never presented as a complete one.

`LLM_TEMPERATURE` is sent only when it is set. Unset, the server applies the model's own
recommended sampling.

### REQ-0055 — a tool that changes anything runs only on the user's confirmation

Every tool declares `"writes": bool` beside its function declaration: true when calling
it changes anything anywhere, upstream included. The registry strips the key before the
tools are offered to the model, and treats a missing or non-boolean value as `true`, so
leaving it out never lets a writing tool through.

A writing tool runs only when the request carries the user's confirmation of that exact
call: the same tool and the same arguments (key order aside). One confirmation runs one
call. Without it the tool is not run and the model receives a JSON error with
`"confirmation_required": true`, which it can explain (REQ-0025).

Every active tool reads. The disabled dataset skill's `query_dataset` sends SQL the model
wrote and is declared as writing, so re-enabling the skill does not make it callable. No
confirmation flow exists in the app yet: a registry is built with none, so today every
writing tool is refused. Offering one at all is a decision still to be taken.


