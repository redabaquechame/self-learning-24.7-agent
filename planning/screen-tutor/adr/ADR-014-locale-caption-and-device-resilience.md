# ADR-014: locale, caption and device resilience

**Status:** Accepted for implementation  
**Decision date:** 2026-09-15

## Context

A realtime tutor can harm comprehension when it silently treats an untested
language, accent, term or device as equivalent to a qualified one. Speech
recognition is probabilistic. Correcting its visible caption must not erase the
raw recognition that explains a later decision, and a newly selected audio
device must not inherit capture permission from the previous device.

## Decision

1. Every locale pack preserves source language, target language, fallback
   locale and terminology uncertainty. `UNTRANSLATED` terms retain their source
   spelling and cannot invent a preferred translation.
2. A candidate pack carries no qualification references. A qualified record
   requires provider, content-review, human-comprehension and device-matrix
   references, and callers must independently verify those exact references
   before suppressing visible fallback.
3. Raw caption text, origin, language and code-switch spans are immutable.
   Corrections are bounded append-only revisions with actor and reason. The
   visible caption may use the latest correction while evidence retains raw
   recognition.
4. Speech rate is bounded from 0.5 through 2.0. Push-to-talk, barge-in, stop
   speech and text fallback each have a distinct keyboard equivalent.
5. Any device identity change synchronously pauses capture, advances device
   generation and removes authorization. Only explicit authorization for the
   current device and generation resumes capture.
6. Locale/device qualification matrices represent unrun measurements with
   `null`, never zero. A passed row requires all required evidence tiers and
   positive authority, barge-in and device-change controls.

## Failure criteria

- Reject malformed locale tags, duplicate terms or sources, unsupported
  uncertainty values, invented translations and self-qualified candidate packs.
- Reject caption histories that rewrite raw text, overlap or omit language
  spans, reuse correction identity or exceed bounds.
- Reject speech rates outside the stated range and stale device authorization.
- Reject a passed matrix with missing measurements, evidence tiers, content
  digest or failed control; refuse any claim that offline fixtures establish
  provider, content, human, acoustic or assistive-technology quality.

## Consequences

- Python and native contracts can test fallback, terminology, caption history,
  input alternatives and device-change state without recording a person or
  contacting a provider.
- The candidate `en-CA` pack and matrix are scaffolding with unknown metrics.
  They do not declare even English qualified.
- Provider accuracy, code-switch recognition, comprehension, accessibility and
  supported-device performance remain separate external qualification work.

## Reversal

Disable locale-specific voice output, pause every capture guard, show the text
fallback in the last independently verified locale, retain raw caption and
correction evidence, and preserve unrelated learner history and source state.
