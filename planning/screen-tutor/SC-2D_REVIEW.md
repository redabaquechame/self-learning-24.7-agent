# SC-2D native session and onboarding review

**Scope:** native five-step synthetic onboarding surface, progressive intent
selection, source-safe in-memory draft/goal continuity, distinct close/stop/
cancel operations, capability disclosure, access keys, automation names, focus,
text scale and reduced-motion state.  
**Current verdict:** locally compiled and native-offline verified mechanism;
installed visible journey and usability qualification remain open.

## Resolved findings

1. **Closing the panel could erase work or cancel another operation.** Panel
   close changes only `PanelOpen`; draft, goal, sharing, speech and task remain.
2. **A retained question could use the old app's coordinates.** A source change
   increments `SourceEpoch` and clears `ObservationRevision` while preserving
   the learner-authored draft and goal.
3. **“Stop” could have ambiguous reach.** Speech, sharing and task cancellation
   have separate methods and labels; `StopAll` explicitly composes them.
4. **No microphone could become a dead end.** Capability messages retain the
   text route and clearly describe the local/static experience when live
   answers are unavailable.
5. **Learning modes could expose implementation language.** Each mode has one
   learner-facing sentence and no model, pipeline, grant or evaluator detail.
6. **First use could front-load setup.** The checked XAML presents five ordered
   steps over a test-owned synthetic source and says voice/accounts are optional.
7. **Keyboard users could lose position.** Buttons have access keys, the grid
   has cyclic tab navigation, and summon/mode/stop paths return focus to the
   question control or record it as the reopen target.
8. **Accessibility preferences could become unchecked free-form values.** Text
   scale is bounded to 1.0–2.0 and reduced motion is an explicit boolean state.

## Evidence

- The pinned .NET 10.0.401 build compiles the actual WPF XAML and source with
  zero warnings and zero errors.
- `SessionJourneyTest` exercises no-mic/offline disclosure, source selection and
  observation invalidation, close/reopen, speech stop, task cancel, sharing
  stop, five modes, accessible metadata, scaling and reduced motion.
- The STA test instantiates the real `Onboarding` XAML, rejects an out-of-order
  step, checks every automation name, completes all five steps, and resets.
- The same native executable retains the previous canvas, audio-control and
  real test-owned capture witnesses.

## Evidence boundary

SC-2D is not accepted. SC-2A and SC-2B remain unaccepted dependencies. The
onboarding checklist was instantiated in a test process; no installed novice
used summon, private source selection, provider answer, visible production
highlight, circle and Stop end to end. No real screen reader, keyboard-only
observer, 200% OS scaling, reduced-motion OS setting, two-monitor transition,
interrupted session, time-to-value study, deployment or release test ran.
