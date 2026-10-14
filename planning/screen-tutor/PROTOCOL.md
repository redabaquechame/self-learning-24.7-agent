# Screen Tutor protocol v1

**Packet:** SC-0B  
**Wire limit:** 1 MiB  
**Current protocol:** 1.1  
**Compatible floor:** 1.0  
**Feature default:** disabled

`tutor_contracts.py` is the canonical executable schema. The checked-in
`companion/windows/contract-probe/tutor-contracts.v1.json` is generated from
that module. The native probe parses that same file; it is not a second
handwritten schema.

## Authority boundary

Records may name host-issued observation, budget, retention, and consent
references. They never contain a native handle, secret, signing key, tool
object, or executable grant. Validation reads an immutable host grant view and
returns `grant_created: false`. It never imports or calls `grants.grant`.

An owner may explicitly request a stronger mode only when the existing grant
view already contains every required capability. A learner, model, page, or
system profile cannot upgrade the mode. Moving to a weaker mode reduces the
effective capability view.

| Mode | Effective capabilities |
|---|---|
| EXPLAIN | observe, explain |
| GUIDE | observe, explain, annotate |
| COLLABORATE | observe, explain, annotate, input |
| DELEGATE | observe, explain, annotate, input, execute |

`LEARN` changes teaching and evidence policy. It does not add tools.

## Records

- `fleet.tutor.session_grant_view.v1` is a time-bounded view of existing host
  authority. It binds owner, tenant, project, sources, destinations, policy
  references, consent, capabilities, and cancellation generation.
- `fleet.tutor.observation.v1` binds the user, tenant, project, source,
  source revision, capture epoch, consent revision, geometry revision,
  monotonic freshness window, artifact digest, modalities, and retention.
  Native picker receipts use `SELECTED_SURFACE` when Windows intentionally
  keeps the selected window-versus-display type opaque to the application.
- `fleet.tutor.request.v1` binds the question and intent to observation and
  source IDs, mode, consent revision, cancellation generation, budget
  reservation, retention policy, monotonic deadline, research scope, and
  bounded output preferences.
- `fleet.tutor.instruction.v1` carries grounded claims and annotations. GUIDE
  and EXPLAIN require `execution_request: null`.
- `fleet.tutor.learner_evidence.v1` distinguishes USER, AGENT, and SHARED work
  and records assistance. It does not carry a score or mastery judgment.

Identifiers use ASCII letters, digits, underscore, or hyphen and contain 1 to
128 characters. UTC audit timestamps end in `Z`. Runtime expiry uses integer
monotonic milliseconds. Required fields must be present and non-null. Unknown
fields, duplicate JSON keys, booleans in integer fields, and NaN or infinity
are rejected.

## Cancellation and source change

Every asynchronous operation captures a cancellation generation. The host
checks it before capture, retrieval, provider dispatch or charge, render,
downstream handoff, and action. A mismatch stops early work with
`CANCELLED_GENERATION` and suppresses late work with
`SUPPRESS_STALE_RESPONSE`. A changed capture epoch, source revision, consent
revision, or geometry revision independently invalidates dependent work.

## Version behavior

Version 1.0 and 1.1 peers are compatible. Unknown major versions and future
minor versions refuse with `UNSUPPORTED_PROTOCOL`; they never silently drop
authority fields. Upgrade and downgrade fixtures only change the negotiated
protocol envelope. The v1 record bindings remain intact.

## Error dictionary

| Code | Meaning |
|---|---|
| `INVALID_JSON` | strict JSON decoding failed |
| `MESSAGE_TOO_LARGE` | message exceeds one MiB |
| `INVALID_SCHEMA` | shape, type, enum, limit, or required value failed |
| `UNSUPPORTED_PROTOCOL` | version cannot be negotiated safely |
| `REFUSE_CONTEXT_ACCESS` | user, tenant, or project differs |
| `REFUSE_PERMISSION` | grant view lacks a capability or contains an unknown one |
| `REFUSE_MODE_ESCALATION` | upgrade did not come from the owner |
| `STALE_CONSENT` | consent revision differs |
| `STALE_SOURCE` | capture epoch, source ID, or revision differs |
| `STALE_GEOMETRY` | annotation geometry is no longer current |
| `CANCELLED_GENERATION` | work started in an old generation |
| `EXPIRED_OBSERVATION` | monotonic freshness window ended |
| `SUPPRESS_STALE_RESPONSE` | late result must not render or continue |
| `REFUSE_MODE_ACTION` | Explain or Guide attempted execution |

Validators return `{allowed, reason_code, record_id}` plus bounded details.
Denied records must not be forwarded, charged, rendered, handed off, or acted
on. `NOT_ASSESSABLE`, `ASSISTED`, `INDEPENDENT_ELIGIBLE`, and `INVALIDATED`
describe assessment eligibility; none declares correctness or mastery.

## Session transitions

The normal cycle is `DORMANT → SELECTING → READY → OBSERVING → THINKING →
PRESENTING → READY`. `PAUSED`, `SOURCE_UNAVAILABLE`, `AWAITING_USER`,
`STOPPING`, `CLOSED`, and `ERROR` are explicit states. Every event/state pair
uses the closed transition table in `validate_session_transition`; the tutor
session does not alter the separate durable Fleet task lifecycle.
