# Decisions

Architecture decision records: **why a technical choice was made here**, when the reason
is not derivable from the code and would otherwise be re-litigated.

One file per decision, named `ADR-####-short-slug.md`, with this shape:

```markdown
# ADR-0001 — <the decision, as a statement>

**Date:** <ISO-8601>
**Status:** accepted | superseded by ADR-####

## Context
<what forced a choice. The constraint, and what had already been tried.>

## Decision
<what was decided, in the imperative.>

## Consequences
<what this costs, what it forecloses, and what will tempt someone to undo it.>
```

## What is not an ADR

- **A requirement.** What the product must do belongs with the requirements, where it can
  be traced to a test. An ADR is measured by nothing.
- **A rule with a referent that something already measures.** If a statement could carry
  an identifier and a test that names it, put it where that measurement happens. Deciding
  it here hides it from the report.
- **A procedure.** That is `.agents/playbooks/`.
- **A fact about the code.** That is `.agents/knowledge/`.

An ADR is immutable once accepted. It is superseded by a later ADR that names it, never
edited to say something else.

## The records

| | Decision | Status |
|---|---|---|
| [ADR-0001](ADR-0001-fake-every-external-boundary.md) | the test suite fakes every external boundary | accepted |
| [ADR-0002](ADR-0002-tests-describe-the-code-not-the-intent.md) | the first tests describe the code, and the requirements are distilled from them | accepted |
| [ADR-0003](ADR-0003-identity-comes-from-the-proxy.md) | identity is established by the proxy, not by this service | accepted |
| [ADR-0004](ADR-0004-one-hour-not-a-window.md) | appliance advice names one hour, not a window | accepted |
| [ADR-0005](ADR-0005-skills-are-built-per-request.md) | the skill registry is built per request from the caller's token | accepted |
| [ADR-0006](ADR-0006-requirements-carry-identifiers.md) | requirements carry identifiers and tests declare them | accepted |
| [ADR-0007](ADR-0007-the-database-layer-is-tested-on-sqlite.md) | the store's SQL is tested on SQLite by default and PostgreSQL in CI | accepted |

ADR-0003, ADR-0004 and ADR-0005 were written on 2026-08-15 and record decisions the code
had already embodied for some time. They are dated by when they were written down, not by
when they were taken — an ADR is a record, and an undated one is worse than a late one.
