# ADR-017: Scope context by purpose and keep connectors optional

- **Status:** Accepted for implementation
- **Date:** 2026-09-15
- **Packet:** SC-5A

## Context

Cross-application tutoring becomes useful when a learner explicitly brings a
file, message, meeting note or selected screen into the current task. It also
creates a direct cross-account and cross-project disclosure risk. A derived
summary can preserve that risk after the source is removed, and imported text
can contain instructions that attempt to influence the tutor or authorize an
action.

Highlight was proposed as inspiration and as a possible optional bridge.
Current public material documents product connections and data practices, but
the inspected sources do not establish a maintained commercial private-context
API with authentication, scopes, export/deletion semantics, versioning and
support. The exact research result is recorded in `HIGHLIGHT_DECISION.md`.

## Decision

1. The platform owns the context contract and remains usable with no connector.
2. Every source must be explicitly selected and bind exact user, account,
   tenant and project identities, source revision, content digest, observation
   time, access state and deletion eligibility.
3. Capture, transmit and retain are independent allowlists. Capturing an item
   does not imply that it may be transmitted or retained.
4. Imported content is data. Its instructions are never executable and grant
   no action, approval, permission or trust authority.
5. A summary carries immutable references to every source and cannot claim a
   trust level above its least-trusted source. A summary is excluded from a
   request if any source is detached, stale or outside the transmit scope.
6. Contradictions remain visible and unresolved. They are included only when
   both source items are inside the current transmit scope.
7. Removal, revocation and account changes wipe attached content, advance the
   context generation and invalidate old request views and derived summaries.
   A detached item ID cannot silently reattach within the session.
8. Draft and goal text may survive an account change because they are explicit
   user continuity fields. Old source references never survive as current.
9. A connector adapter may be added only against a current supported contract.
   Removing an adapter must revoke its handles without disabling the core route.
10. This component owns no background observer, global capture, network client,
    provider call, screen reader or action executor.

## Failure criteria

The decision fails if context can attach without explicit selection; if user,
account, tenant or project mismatches enter a view; if capture implies transmit
or retain; if imported text gains instruction or action authority; if a summary
raises trust or loses source provenance; if removal, revocation or account
switch leaves an old view usable; if detached content silently reappears; if a
connector becomes required for the core route; or if any Highlight adapter is
built without the supported contract listed in `HIGHLIGHT_DECISION.md`.

## Consequences

The context surface fails closed when provenance is incomplete and carries
some repeated metadata in derived records. That repetition is intentional: it
lets a consumer inspect the source boundary without trusting mutable ambient
state. Continuous desktop memory and account-wide history copying are outside
this decision.

## Verification

- T058 checks explicit selection, exact identity scope and inert imported
  instructions.
- T059 checks trust ceilings, provenance, contradiction visibility, tamper and
  removal invalidation.
- T060 and X011A check that the core route works without Highlight, a connector
  or global capture.
- T061 and X011B check transmit filtering, revocation and account switching.
- A selective mutation removes only project filtering while leaving retrieval
  functional; T058 must fail.
- The compiled Windows companion contract independently checks the same scope,
  removal, account-switch and optional-connector boundary against synthetic
  records.

## Qualification boundary

These checks use deterministic synthetic sources. They establish local and
compiled native contract mechanics. They do not establish a maintained vendor
API, real connector revocation/deletion, a visible private-source picker
journey, OS accessibility behavior, provider behavior, independent content
review, deployment or release readiness.

## Reversal

Disable and remove an optional connector adapter, revoke and wipe every handle
it issued, and keep the platform-owned source contract enabled. If the native
boundary itself must be rolled back, disable its feature registration and purge
its transient context stores; do not migrate private context into the legacy
Fleet memory or preserve stale derived summaries.
