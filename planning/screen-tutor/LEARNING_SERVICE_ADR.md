# ADR: One learning service contract across every product surface

**Status:** Accepted for in-process implementation  
**Decision date:** 2026-09-15  
**Contract version:** `learning.v1`

## Problem and decision

Main Learn, the native companion, the standalone portal, and the embed SDK need
the same courses, assignments, sessions, attempts, evidence, permissions, and
success decisions. A separate backend or policy copy per interface would let
branding, deployment, and frontend drift change authority or learning credit.

Use one logical learning service in the existing Python process. Every surface
gets a thin adapter over `learning_contracts.LearningService`. The host seals
principal, tenant, policy revision, grant revision, course revision,
entitlements, and bounded local capability names before it creates an adapter.
Payloads cannot supply or override those fields. Extracting a network service is
conditional on measured scaling, isolation, or deployment need and must preserve
`learning.v1` semantics.

## Concrete reuse map

| Concern | Current owner | Learning-service use | Explicit boundary |
|---|---|---|---|
| Organization identity and roles | `org.py` | Host resolves a principal and its organization role before binding | No second identity store; this packet does not add public authentication |
| Standing external authority | `grants.py` | Host binds a grant revision, while effects continue to call the existing grant checker | A remote portal never receives local grant records or credentials |
| Mission and task lifecycle | `mission.py`, `goal.py`, `contract.py` | Future handoff proposes work into the existing task lifecycle | Learning completion and agent task completion remain different records |
| Model routing, budgets, calls | `modelgateway.py` | Future tutoring calls use the existing metered gateway | The learning adapter cannot select a provider or carry a key |
| Durable event and evidence authority | `contract.py`, `fileauth.py`, existing JSONL ledgers | This packet defines ordered typed learning events; persistence adapters later use existing atomic/append boundaries | In-memory SC-0D witnesses are not durable-service or deployment proof |
| Browser and computer-use authority | `computeruse.py`, `computersession.py` | Native/session adapters may reference separately granted observations | A web token cannot become a local capture or input grant |
| Agent mastery | `mastery.py`, `capability.py` | Reuse provenance concepts only | Human attempts never call agent pursuit or inherit agent mastery verdicts |

## Contract ownership

The service owns course, assignment, session, attempt, submission, evidence,
cancellation, capability, idempotency, pagination, and event-contract semantics.
Existing authorities continue to own identity, roles, external grants,
credentials, model budgets, file writes, execution, effects, and agent tasks.
Frontends own rendering, navigation, accessible interaction, and allowlisted
branding fields only. They do not decide permission, score, mastery, retention,
or task success.

The operation catalogue names reserved future operations explicitly. A reserved
operation fails closed until its owning packet implements and tests it. Naming
an operation in the catalogue is not a claim that it works.

## Version, retry, cursor, cancellation, and retention rules

- Commands use exactly `learning.v1`; unknown versions and fields fail closed.
- Mutations require an idempotency key scoped to principal, tenant, operation,
  and payload digest. Same bytes replay the same receipt. Different bytes with
  the same key return a conflict.
- Record IDs exclude surface and branding, so equivalent authorized commands
  through separate adapters create equivalent authoritative records.
- Lists use stable `(sequence, id)` ordering and an opaque HMAC cursor bound to
  principal, tenant, kind, and offset. Cursor editing or cross-tenant reuse fails.
- Cancellation is a distinct durable-shaped record. It cannot cancel submitted,
  scored, or already-cancelled work, and it cannot erase prior events.
- Every record names a bounded retention class. Later persistence packets must
  implement export, deletion, derived-cache invalidation, and durable readback
  before those reserved operations become available.
- Version skew currently has one rule: exact `learning.v1` or refusal. Add a
  compatibility window only with bidirectional fixtures and rollback evidence.

## Surface and native-boundary rules

All four adapters call the same service. Brand fields are limited to title,
logo URL, and accent color and reject executable content. Adapter metadata may
name the surface, but authoritative records do not. Main and portal requests
therefore cannot diverge through presentation settings.

Native permissions remain local and per session. The binding may carry bounded
capability names for host-side discovery, never reusable grant tokens. Portal
and embed capability responses report no native capture authority. SC-1A owns
the authenticated local handshake and consent implementation.

## Failure criteria

- A payload-supplied principal, tenant, role, entitlement, grant, policy, score,
  verdict, or pass state is accepted.
- Branding changes an authoritative record, permission, or learning outcome.
- A cross-tenant reference or cursor reveals or changes a record.
- Idempotent retry creates a second record, or conflicting reuse is accepted.
- Any surface implements policy or success logic that differs from this module.
- A submitted learner attempt becomes passing without the separate independent
  assessment path owned by SC-2F.

## Rollback and extraction trigger

Disable adapter registration while preserving versioned records. The core and
existing product flows continue to run because this module is additive. Extract
the service only after measurements identify a concrete process-isolation,
scaling, or independent-deployment requirement; preserve contract fixtures and
run both implementations against identical requests during migration.
