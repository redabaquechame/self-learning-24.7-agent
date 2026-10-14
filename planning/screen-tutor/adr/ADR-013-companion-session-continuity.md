# ADR-013: companion session continuity and distinct controls

**Status:** Accepted for implementation  
**Decision date:** 2026-09-15

## Context

The flagship companion has several operations that look similar but have
different consequences. Closing its panel, stopping speech, stopping sharing,
cancelling a Fleet task and stopping all active work cannot silently stand in
for one another. A source change must invalidate old screen observations while
preserving the learner's permitted draft and stated goal.

## Decision

1. `SessionViewModel` owns the visible session semantics. Draft text and the
   learning goal survive panel closure, source replacement, speech stop,
   sharing stop and task cancellation for the life of the permitted session.
2. Source ID, revision and observation revision are separate. Selecting a
   different source increments the source epoch and clears the observation.
   Stale screen state cannot follow a retained draft into another application.
3. Panel close changes panel visibility only. Speech stop increments the speech
   epoch only. Sharing stop clears source-derived state only. Task cancellation
   clears the current task only. Stop All composes the three explicit stops.
4. Explain, Show, Teach, Assess and Collaborate remain distinct intents with
   plain-language descriptions. Text input is always available. Missing
   microphone or provider capability is stated directly and routes to the
   local/static text experience.
5. The native shell exposes access keys, automation names, cyclic tab order,
   question-focus restoration, text scale from 100% to 200%, and reduced-motion
   state. The first-use control lists summon, synthetic source, ask, show/circle
   and Stop in a fixed order, with voice and account connections optional.

## Failure criteria

- Panel close must not erase a permitted draft/goal or cancel sharing, speech or
  an unrelated task.
- Source changes must not preserve an observation revision from the prior
  source; stop/cancel operations must not exceed their stated scope.
- Reject invalid identities, out-of-order onboarding, oversized text and text
  scale outside the declared range.
- Refuse usability, screen-reader, installed-journey, multi-monitor or release
  claims until those evidence tiers run against the exact build.

## Consequences

- Deterministic native tests can distinguish the five lifecycle operations and
  prove source-safe in-memory continuity.
- The WPF XAML compiles with the actual companion and exposes a concrete
  synthetic onboarding surface and accessible control metadata.
- This slice does not establish that a novice completed the installed journey
  or that a screen reader announced every transition correctly.

## Reversal

Remove the onboarding control and intent controls, restore the prior session
window, clear transient source/task/speech state, and preserve only the draft
and goal data allowed by the active retention policy.
