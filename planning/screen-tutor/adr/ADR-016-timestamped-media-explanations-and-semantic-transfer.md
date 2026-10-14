# ADR-016: timestamped media explanations and semantic app transfer

**Status:** Accepted for implementation  
**Decision date:** 2026-09-15

## Context

A caption, one frame, an audio interval and an entire video establish different
facts. Even a correct description becomes stale after a seek or content change.
A demonstrated control also does not retain its identity or coordinates in a
different application window, version, display or accessibility tree.

## Decision

1. Each media explanation binds media, tenant/project, source revision, content
   digest, content epoch, timeline epoch and a transition fingerprint. A current
   check suppresses any mismatch or omitted binding.
2. Every claim declares a bounded interval, kind, modality, certainty and exact
   evidence IDs. Captions report narrator text, frames support visual state,
   media audio supports audio events, and visible transitions require distinct
   before/after frames.
3. Processed coverage lists caption/audio intervals, frame timestamps,
   authorization intervals and explicit gaps. Full-source mode never implies
   full understanding; sparse or missing evidence returns named limitations.
4. A decisive interval with insufficient before/after frames yields a bounded
   retrieval plan. The plan says retrieval was not performed and cannot become
   evidence until the media index receives actual bytes.
5. App transfer consumes a qualified, digest-bound teaching-pack record and a
   current application observation. It runs semantic-first grounding against
   current candidates. Tutorial frame coordinates are not an input and cannot
   be replayed.
6. Ambiguous current controls abstain. Unsupported app versions and candidate
   packs refuse. A practice handoff preserves pack/observation lineage and never
   claims learner success.
7. Playback changes are data-only intents. They require a current explicit user
   grant bound to media/source/timeline and never execute inside this module.

## Failure criteria

- Reject unknown fields, malformed or duplicate identities, invalid intervals,
  current evidence with foreign source bindings, out-of-rights windows and
  unbounded claims or audio rows.
- Reject a caption used as pixel observation, a contested caption presented as
  an uncontested fact, and a visible transition backed by fewer than two frame
  timestamps.
- Suppress explanations after seek, content/source/ad transition drift, or when
  any required timeline field is missing.
- Reject app transfer without qualified human-reviewed pack scope, exact app
  version coverage and current semantic application evidence.
- Reject playback authority inferred from tutorial, caption or assistant text.

## Consequences

- T052-T057 and X010A/X010B can exercise the complete data contract with
  synthetic bytes and no external media, private screen, provider or playback
  action.
- Provider generation, native target accuracy, content quality, learning and
  real media acquisition remain separate qualification gates.
- The candidate `video-transfer-v1` pack validates mechanically but stays
  unassignable until independent subject review and qualification are recorded.

## Reversal

Disable the media-tutoring route, invalidate active explanation/timeline
bindings, preserve only permitted indexed evidence according to retention
policy, and fall back to separately authorized text or current-screen guidance.

