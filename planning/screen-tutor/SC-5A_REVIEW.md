# SC-5A scoped context review

**Scope:** explicit context selection, identity and purpose scope, provenance,
summary trust, contradictions, removal/revocation, account changes, continuity
and optional connector behavior.  
**Review dimensions:** privacy, security, correctness, performance and
maintainability.  
**Current verdict:** local and compiled-native synthetic mechanics pass;
dependency, real connector and visible native journey qualification remain
open.

## Resolved findings

1. **Selected data could cross projects or accounts.** Attachment validates the
   exact user, account, tenant and project. T058 covers each mismatch, and the
   project-filter mutation is caught.
2. **Imported instructions could gain authority.** Every public item is marked
   `UNTRUSTED_CONTEXT_DATA` and `instructions_executable: false`. No content
   string creates approval or action authority.
3. **Capture could imply transmission or retention.** The three purposes are
   independent allowlists. A selected screen fixture can be captured while
   remaining absent from the request view and retention policy.
4. **A summary could launder trust.** Summary trust cannot exceed the least
   trusted source. It binds source item, origin, revision, digest, observation
   time, access and deletion eligibility.
5. **Derived text could leak a non-transmittable source.** Request assembly now
   excludes a summary unless every source is attached and inside the transmit
   scope. Contradictions follow the same rule.
6. **Removal could leave stale caches usable.** Removal and revocation wipe
   source bytes, advance generation and exclude dependent summaries and
   contradictions. Exact current-view comparison rejects modified serialized
   views.
7. **Context could silently return after deletion.** Historical item IDs remain
   reserved for the session, so reattachment conflicts rather than restoring
   bytes in the background.
8. **Account switching could carry private source references forward.** All
   attached items are detached and wiped; the generation changes. Explicit
   draft and goal text remain, with `source_references_current: false`.
9. **A third-party outage could break tutoring.** The platform-owned response
   route returns ready with no connector. No Highlight adapter, background
   observer or global capture path exists.
10. **Native and Python behavior could diverge.** The compiled native boundary
    separately exercises inert content, project isolation, transmit filtering,
    removal, account switch and connector absence.

## Evidence

- `tests/test_tutor_context.py` passes T058–T061 and X011A/X011B offline.
- The project-filter selective mutation is caught; no fault-injection bytes
  remain after restoration.
- `ScreenTutor.ContractTests` builds with zero warnings and zero errors and
  prints the native T058–T061/X011 witness.
- Feature-off, frontend, doctor, packaging, invariant, environment-lock and
  native-session regression checks pass after integration.
- The shipped package contains source and tests while excluding native build
  outputs and private runtime context.

## Highlight decision

`HIGHLIGHT_DECISION.md` records current primary-source research. No supported
private-context embedding contract was established, so the adapter remains
absent. This absence is an explicit supported configuration exercised by the
tests.

## Evidence boundary

SC-5A is not accepted because SC-1C content qualification remains open and the
required real native context journey has not run. No real connector account,
private file/message/meeting, Highlight endpoint, background observation,
provider, independent reviewer, signed installer, deployment or release was
used. The native witness is compiled but deterministic and synthetic. The
evidence does not establish production privacy, vendor compatibility, teaching
quality, learning gains or superiority over any product or human expert.
