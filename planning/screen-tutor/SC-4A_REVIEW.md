# SC-4A offline authorized media-index review

**Scope:** source authorization and bounds, caption/frame provenance, explicit
coverage gaps and transitions, content/timeline epochs, seek/content-change
invalidation, bounded adaptive sampling, expiry/revocation and modality-honest
claim support.  
**Review dimensions:** security, correctness, performance, maintainability.  
**Current verdict:** locally verified for deterministic synthetic fixtures;
provider and live-media qualification remain open.

## Resolved findings

1. **A URL or upload label could substitute for retrieved evidence.** The module
   has no fetcher and records frames only from provided nonempty bytes with a
   computed digest. Retrieval plans are stored separately from processed rows.
2. **A seek could reuse an old explanation.** Seek increments timeline epoch;
   support and ingestion reject an older epoch even when every other field
   matches.
3. **A playlist/source replacement could rewrite history.** Replacement needs a
   new source revision and content digest, advances content/timeline epochs and
   leaves earlier rows bound to their original values.
4. **Captions could masquerade as seeing a menu click.** Visual support requires
   an actual frame in the queried interval. The selective mutation that uses
   caption presence instead is caught by `test_tutor_media_index.py`.
5. **Missing captions could be smoothed over.** Gaps retain interval, modality
   and reason. Caption rows retain language, raw/contested/corrected state and
   the exact provenance reference.
6. **Sampling could grow with video duration or transition count.** The planner
   consumes a finite request budget, deduplicates timestamps and prioritizes a
   fixed neighborhood around declared transitions.
7. **Revoked or expired access could remain live.** Access is checked on index
   creation and again before each caption/frame ingestion. Revocation advances
   timeline identity and prevents new evidence.
8. **Rights could cover the title but not the requested interval.** Every
   caption, frame and gap must lie inside one explicit allowed interval.

## Evidence

- X025A offline indexes exact synthetic caption/frame provenance, gaps and
  scene/ad transitions, prioritizes transition samples within budget, preserves
  old content lineage and invalidates stale seek/content epochs.
- X025B offline proves a transcript-only index returns
  `VISUAL_EVIDENCE_MISSING`; expired, denied, revoked and out-of-rights sources
  produce no evidence.
- The caption-as-visual selective mutation is caught.

## Evidence boundary

SC-4A is not accepted because SC-1B and SC-1C remain unaccepted dependencies and
the required provider tier did not run. The only media is a small synthetic JSON
fixture and in-memory test bytes. No external upload/URL/current-screen source,
codec, decoder, downloader, expiring credential, real seek, advertisement,
caption track, audiovisual model, provider cost/latency test, deployment or
release test ran. This review makes no full-video understanding, production
scale, accuracy, accessibility or market-superiority claim.
