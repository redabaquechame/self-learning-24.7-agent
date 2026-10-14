# ADR-010: Revision-bound grounding and inert overlays

**Status:** Accepted for implementation  
**Decision date:** 2026-09-15

## Context

A pointer that was correct for an earlier frame can become harmful after a
window moves, a tab changes, content scrolls, DPI changes, or a control is
removed. Visual matching also becomes ambiguous when the same label appears in
several places. Companion graphics must never become executable content or be
mistaken for evidence from the application being taught.

## Decision

Use one explicit coordinate chain from source pixels through the selected crop
and model input to desktop device-independent pixels. Bind every target and
overlay ticket to the exact observation, source ID, source revision, capture
epoch, geometry revision, mode, target and finite expiry. Prefer a unique
accessibility target. Permit visual fallback only after its adapter and frozen
benchmark are qualified; otherwise abstain.

Accept only the closed inert primitive set `RECT`, `ARROW`, `POINT`, and
`LABEL`. Validate every field, target, coordinate, color, stroke, count and
lifetime before scheduling. The native renderer is hit-test transparent and
has no input privileges. Any binding change or expiry suppresses the complete
ticket. Mark companion overlay layers and remove them from later application
observations and target selection.

## Failure criteria

- A stale geometry or capture revision leaves any primitive renderable.
- Duplicate semantic or equally scored visual targets cause a guessed pointer.
- An unqualified visual adapter produces a grounded target.
- A script, URI, callback, unknown field, unbounded style or mismatched target
  reaches the renderer.
- A negative desktop origin, selected crop, resize, or DPI scale is omitted
  from the transform.
- Overlay pixels become application evidence or a target for later guidance.

## Reversal

Disable overlay scheduling and return text guidance with the same qualified
source citations. Keep capture, source binding and learner evidence active;
they do not depend on the visual layer.
