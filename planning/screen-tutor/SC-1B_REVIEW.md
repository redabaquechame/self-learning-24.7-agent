# SC-1B qualified image gateway review

**Scope:** the isolated tutor image route, ephemeral image references, provider
capability declarations, budget reservation, usage reconciliation, cancellation,
source freshness, and bounded answer validation.  
**Review dimensions:** security, correctness, performance, maintainability.  
**Current verdict:** locally verified and reviewed; live provider qualification is
blocked until the owner supplies an explicit provider route and spend budget.

## Resolved findings

1. **The general model route could accidentally inherit image support.** The
   ordinary context contract still rejects every non-text part. The tutor route
   requires a private one-shot dispatch authority created only after all image,
   source, capability, accounting, price, deadline, and budget checks pass.
2. **A URL or path could become an unintended image fetch.** The gateway accepts
   only a process-local `observation://` reference issued by its injected
   `EphemeralImageStore`. It has no URL or filesystem resolver.
3. **A provider call could escape cost control before image usage was known.**
   The route requires an explicit image-unit formula and token accounting
   contract, reserves the conservative maximum before dispatch, and refuses
   providers whose price or accounting ceiling is unknown.
4. **Retries or duplicate completions could double-charge.** Request IDs,
   dispatch authorities, image references, and reservations are one-shot.
   Reconciliation replaces one reservation exactly once; a duplicate settlement
   cannot append another charge.
5. **A late answer could describe a different screen.** Source ID, source
   revision, capture epoch, cancellation, and deadline are rechecked before each
   provider attempt and after the response. A stale result is suppressed.
6. **Malformed or incomplete provider usage could appear qualified.** Missing,
   non-finite, inconsistent, or under-estimated usage cannot produce a qualified
   answer. Unknown usage settles at the reserved ceiling.
7. **Screen content could act as instructions.** The system message declares the
   image untrusted material and forbids following instructions visible inside it.
   The user message carries the exact source binding and one bounded data image.
8. **A capable model name alone could authorize the route.** Qualification also
   requires an explicit enable flag, allowlisted model and MIME format, image
   unit formula, token-accounting statement, finite price or explicit free status,
   and exactly one configured tutor role.

## Security assessment

- Image bytes live in one process-local byte buffer and are overwritten on
  rejection, consumption, eviction, expiration, or store close.
- PNG and JPEG headers are parsed locally. Media is capped at 10 MiB, 8192 pixels
  per side, and 16 megapixels before a provider request can exist.
- No browser fetch, remote URL fetch, local path read, tool call, model fallback,
  or role escalation exists on the qualified route.
- The observation reference binds source ID, source revision, capture epoch,
  MIME type, dimensions, length, digest, expiry, and one-shot consumption.

## Correctness assessment

- A loopback provider exercised the production HTTP adapter and received exactly
  one data URL alongside the bound source metadata and no tools.
- Text tokens and image input units are accounted separately. The observed
  provider usage replaced the reservation with the exact calculated charge.
- Capability, format, accounting, pricing, dimensions, budget, duplicate ID,
  stale source, cancellation, malformed answer, and missing usage negatives all
  failed at their owning boundary.
- A 429 response retried through the real adapter under the same reservation;
  cancellation before the retry prevented the next dispatch.

## Performance assessment

- The store rejects oversized bytes and dimensions before base64 expansion or
  network dispatch. A consumed entry is removed immediately.
- Requests carry one image only and never enter normal routing, fallback, tool,
  or escalation loops.
- Retry checks are constant-time source/cancellation/deadline predicates, and all
  attempts share one conservative reservation.

## Maintainability assessment

- `tutor_gateway.py` owns the qualified route; the general context contract,
  provider HTTP adapter, spend ledger, and agent loop retain their existing roles.
- Provider qualification is declarative and fails closed when a required field
  is absent. The accepted provider/model pair is exact rather than heuristic.
- The immutable original baseline lock remains intact. The reviewed SC-1B lock
  records the new protected hashes used by feature-off regression.
- Tests are registered in the authoritative suite and evidence inventory; the
  duplicate-reservation guard is registered in the mutation harness.

## Evidence boundary

SC-1B has verdict `LOCAL_VERIFIED_REVIEWED_PROVIDER_BLOCKED`. Its offline and
loopback requirements are proven. The loopback service is a local test double;
it does not establish a real provider's current multimodal behavior, bill, data
handling, latency, availability, or model quality. T021 and packet acceptance
remain blocked until the owner explicitly selects a provider route and budget.
No deployment, release, privacy, efficacy, usability, or market-superiority
claim follows from this review.
