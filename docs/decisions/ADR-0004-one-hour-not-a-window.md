# ADR-0004 — appliance advice names one hour, not a window

**Date:** 2026-08-15
**Status:** accepted

## Context

Recorded after the fact. "When should I run my appliances?" is one of the twelve starter
prompts. The forecast data is hourly community net exchange, and the honest summary of it
is a range — "there is surplus this afternoon". Users acted on ranges by not acting.

## Decision

The energy forecast ranks upcoming positive-surplus hours and returns **at most three**,
best first, plus a `suggestion` sentence naming the single best one. The system-prompt
fragment instructs the model to suggest that specific hour "rather than a wide window",
and the tool result repeats the instruction so it survives summarisation.

## Consequences

Advice is actionable and, when the forecast is wrong, specifically wrong — a named hour
that turns out cloudy is more visibly wrong than "this afternoon" was. That is accepted:
a suggestion nobody acts on has no error rate because it has no effect.

The cap at three is what stops the model reconstructing a window from the list.

What will tempt someone to undo this: a complaint that the assistant is over-confident
about a forecast. The answer is to carry the confidence bounds that are already in the
payload, not to widen the window.

Implementation note, not part of the decision: the `suggestion` sentence has never
actually been produced. See DEFECT-01.
