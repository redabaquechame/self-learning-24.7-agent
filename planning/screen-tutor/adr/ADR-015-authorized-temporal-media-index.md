# ADR-015: authorized temporal media index

**Status:** Accepted for implementation  
**Decision date:** 2026-09-15

## Context

Caption text, decoded frames and a complete video are different evidence. A
media tutor that treats them as interchangeable can attribute a visual action
to narration, reuse guidance after a seek, infer through inaccessible gaps, or
continue after rights expire. Retrieval planning also does not prove that a
planned frame or interval was actually obtained.

## Decision

1. A media source binds tenant, project, media ID, immutable source revision,
   content digest, access method, byte/duration limits, rights, allowed
   intervals and optional monotonic expiry. This module receives authorized
   bytes and captions; it contains no downloader, URL opener, browser or model
   client.
2. Captions carry exact intervals, language, state and provenance. Frames carry
   timestamps, byte count, hash, MIME type and provenance. Gaps and source/ad/
   scene transitions remain explicit records.
3. Every evidence row carries its content and timeline epochs. Seek increments
   timeline identity. Content replacement requires a new revision and digest,
   increments both epochs and preserves prior evidence with its old bindings.
4. Expiry and revocation are checked again before ingestion. Evidence outside
   permitted intervals is refused. An inaccessible source creates no index and
   therefore cannot acquire invented captions or frames.
5. Adaptive retrieval first densifies around declared transitions, then uses
   baseline/fill samples. Every planned timestamp consumes a fixed finite
   request budget. A retrieval decision remains a plan until actual bytes are
   ingested.
6. Caption and visual claim support are queried separately. Caption presence
   cannot satisfy visual support; the reverse also does not create narration.

## Failure criteria

- Reject unknown fields, malformed identities/digests, overlapping rights,
  unbounded media, denied/revoked/expired access or out-of-rights evidence.
- Reject stale source revision, content digest or timeline epoch and duplicate
  caption, frame, gap or transition identity.
- Reject retrieval above budget or a processed-frame record without actual
  nonempty bytes.
- Reject visual-observation claims supported only by transcript/caption rows.
  Refuse external media/provider completeness claims without exact retrieved
  bytes and provider evidence.

## Consequences

- X025A/X025B mechanics can be tested with a synthetic fixture without fetching
  any URL, reading a private screen or contacting a provider.
- The index makes accessed evidence and missing coverage visible and preserves
  seek/content lineage for later SC-4 explanations.
- This slice does not establish codec support, downloader behavior, audiovisual
  understanding, provider quality, live URL authorization or production scale.

## Reversal

Disable media indexing and future SC-4 media explanations, invalidate active
timeline epochs, preserve only permitted caption/frame evidence under its
retention policy, and fall back to separately authorized text or current-screen
evidence without implying full-video coverage.
