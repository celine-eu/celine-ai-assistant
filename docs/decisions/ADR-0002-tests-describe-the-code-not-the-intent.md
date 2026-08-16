# ADR-0002 — the first tests describe the code, and the requirements are distilled from them

**Date:** 2026-08-15
**Status:** accepted

## Context

This repository reached version 1.5.1 with no tests and no written requirements. Adding
tests meant choosing what they assert against. The obvious order — write down what the
service should do, then test that — has one problem at this size: the intent would be
reconstructed from the same reading of the same code, so the tests would assert what the
author already believed and pass.

## Decision

Write the tests against **what the code does**, first. Then distil the requirements from
what writing them revealed, and record the gap between the two as defects.

Where the behaviour found was wrong, the test pins the wrong behaviour, states in its
docstring that it is pinned, and names the defect. Where the correct behaviour is worth
holding as an executable invariant, a second test is marked
`xfail(strict=True)` — so that fixing the defect fails the run until the marker and the
characterisation test are removed together.

## Consequences

It found fifteen defects on the first pass, two of them breaking a user-facing feature
outright — `get_energy_forecast` returning an error whenever there was a surplus to
report, and every unparseable upload returning 500 from inside its own error handler.
Neither would have been found by a test written from intent.

The cost is that `tests/` contains assertions that are deliberately wrong, and a reader
who skims will mistake one for a specification. The mitigations: every such test says so
in its docstring and names a `DEFECT-nn`; `docs/specifications/` states the correct
behaviour and lists what is not satisfied; `.agents/plans/defect-remediation.md` says
that fixing a defect starts by rewriting its test.

This is a decision about a first suite, not a house style. Once the requirements exist,
the next test should be written from them.
