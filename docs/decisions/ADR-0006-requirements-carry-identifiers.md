# ADR-0006 — requirements carry identifiers and tests declare them

**Date:** 2026-08-15
**Status:** accepted

## Context

The harness offers two answers to "is this requirement verified?": its own checker,
reading `docs/specifications/` and `@verifies` tags, or an existing tool declared under
`[traceability]` in `.agents/harness.toml`. This repository had neither — no requirement
identifiers, no traceability provider, and until 2026-08-15 no tests.

Delegating is the right answer for a repository that already has a requirement universe.
This one had nothing to delegate to.

## Decision

Adopt the harness convention. Requirements are `REQ-####` in `docs/specifications/`,
grouped by area. A test declares what it covers with `@verifies REQ-####` in its
docstring. `.agents/harness.toml` stays at its defaults, which is what selects the
harness as the provider.

A new requirement and a test that declares it land in the same change.

## Consequences

The mapping is a projection of the tests and the specifications, so it cannot go stale
the way a hand-maintained matrix does. What it costs is that the specifications have to
be kept honest: a requirement stated and never verified is worse than one not stated,
because the identifier implies it was.

`python -m harness .` is not installed in this checkout, so nothing generates the matrix
yet. The interim is a grep, recorded in the playbook and in
`docs/specifications/index.md`. That is a gap in tooling, not in the convention.

Several requirements are **not satisfied today** — each is named at the foot of its own
specification page, with the defect. Recording a requirement the code fails is
deliberate: it is what makes the defect list mean something.
