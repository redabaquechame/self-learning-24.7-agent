# Code review: SC-0D learning service boundary

**Review date:** 2026-09-15  
**Reviewer:** Current Codex implementation task, structured source review  
**Scope:** `learning_contracts.py`, `tests/test_learning_surface_parity.py`,
`planning/screen-tutor/LEARNING_SERVICE_ADR.md`  
**Verdict:** Approved for SC-0D SOURCE/LOCAL contract scope after fixes below

## Summary

The change adds one stdlib, in-process contract for main Learn, native,
standalone, and embed surfaces. It does not expose a network route or claim the
reserved curriculum, assessment, retention, or handoff operations are built.
Authoritative identity comes from a host-sealed binding, record IDs and retry
semantics exclude branding and surface, and learner submissions remain unscored.

## Critical issues

No unresolved critical issue remains within SC-0D scope.

## Findings resolved during review

| Severity | Dimension | Finding | Resolution and witness |
|---|---|---|---|
| High | Authorization | A same-tenant principal with `learning:read` could list records created for another principal | Default listing now requires creator, learner, or assignee identity; only host-bound `learning:read:any` broadens it. The parity test verifies a second same-tenant principal sees no course record. |
| Medium | Input validation | `payload or {}` converted a falsy list into an empty object | Only `None` receives the empty default; a list now fails the typed-envelope check. |
| Medium | Frontend safety | Branding rejected obvious scripts but allowed insecure logo schemes and untyped colors | Logo URLs now require HTTPS, accent colors require `#RRGGBB`, and executable markers still fail. |
| Medium | Data quality | Due policy, intention, and assistance accepted weakly typed values | Bounded strings and the `ASSISTED`/`INDEPENDENT`/`UNKNOWN` assistance vocabulary are enforced. |
| Low | Cursor correctness | Python booleans could satisfy the integer offset check | Boolean offsets now fail before pagination. |

## Security review

- Payload authority fields are denied before operation dispatch.
- Entitlements are checked from a sealed immutable binding for every operation.
- Tenant references and HMAC cursors fail closed.
- Local capture capability is transport metadata for the native adapter only;
  it is false for portal and embed even if they share the same host context.
- Branding is presentation-only and absent from authoritative records/events.
- No credential, shell, subprocess, network, deserialization, or filesystem
  path is introduced by this module.

## Correctness and failure review

- Strict `learning.v1` envelopes reject unknown fields and versions.
- Mutation idempotency is scoped to principal, tenant, operation, key, and
  payload digest; conflicting reuse fails.
- Records use stable sequence ordering; pagination limits are bounded 1–100.
- Cancellation records rather than erases state and refuses final states.
- `assessment.evaluate` and other future operations are visibly reserved and
  refuse rather than simulating completion.
- A targeted source mutation that changed an unscored submission to passing was
  caught by `test_learning_surface_parity.py`, and the exact source hash was
  restored afterward.

## Performance and maintainability review

Current operations are bounded except in-memory list projection, which is O(n)
and acceptable only for this contract-stage witness. Durable storage work must
add indexed tenant/principal access and bounded event readback before production
scale. Operation and payload catalogs centralize version and entitlement rules;
surface adapters contain no domain branches.

## Qualification limits

This review approves the in-process contract and focused local witnesses. It is
not authentication penetration testing, durable-store qualification, provider
evaluation, native-device qualification, usability evidence, deployment proof,
or release approval. Those remain with their owning packets.
