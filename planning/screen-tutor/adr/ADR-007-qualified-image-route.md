# ADR-007: Sealed qualified image route and spend reservation

**Status:** Accepted for implementation  
**Decision date:** 2026-09-15

## Context

The platform's ordinary model contract intentionally rejects images. Screen
tutoring needs one narrow multimodal route without silently granting every role
image access, fetching arbitrary URLs, losing source freshness, or spending
before a reliable ceiling exists.

## Decision

Keep the general model route text-only. Add a tutor-specific gateway that accepts
only a single-use process-local observation reference. Validate its bytes,
format, dimensions, source ID, source revision, capture epoch, expiry and digest
before constructing the provider payload. Treat visible content as untrusted.

Require the selected provider/model to declare tutor-image enablement, model and
format allowlists, image units, usage semantics, context capacity, and finite
pricing or explicit free status. Require exactly one tutor role. Reserve the
worst-case charge in the spend ledger before the provider adapter is called.
Reconcile that reservation exactly once from consistent returned usage; settle
conservatively and suppress the answer when usage is missing or invalid.

Recheck cancellation, monotonic deadline and source identity before every
attempt and after completion. Never route, fall back, escalate, call tools, fetch
a URL, or return a stale response from this path.

## Failure criteria

- A normal model request accepts an image or a tutor request accepts a URL/path.
- Provider capability, accounting, price, context capacity or exact role is
  missing and a dispatch still occurs.
- A call occurs before reservation, a completion charges twice, or unknown usage
  produces a qualified answer.
- Changed source identity, cancellation or expiry can render a late result.
- Raw bytes, data URLs or visible screen text enter durable logs or spend records.

## Qualification

Offline validation and a loopback service prove the route and accounting
contracts. A separately authorized real-provider test must confirm current API
shape, returned usage and actual billing before SC-1B can be accepted.

## Reversal

Disable `tutor_image_enabled` for every provider. The general text route and
durable spend ledger remain valid; ephemeral observation entries are wiped.
