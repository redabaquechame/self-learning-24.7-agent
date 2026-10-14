# SC-0B contract review

**Scope:** `tutor_contracts.py`, its generated fixture, native fixture probe,
protocol document, and focused test.  
**Review dimensions:** security, correctness, performance, maintainability.  
**Current verdict:** approved for SC-0B source and local contract scope.

## Resolved findings

1. **Malformed field types could escape as Python `TypeError`.** UTC and digest
   fields now establish string type before regular-expression validation.
   A field-by-field malformed-type sweep across all four records reported zero
   uncaught exceptions.
2. **Source kind and modality strings were syntactically valid but not closed
   enums.** Both vocabularies now reject unknown values.
3. **A request ID did not yet bind retry bytes.** Authorization now computes a
   canonical SHA-256 request digest, recognizes an exact replay, and refuses a
   conflicting payload under the same request ID.
4. **Host-issued references were shape-checked but not all compared with the
   host view.** Artifact, budget reservation, and retention references now
   refuse when the host supplies an allowlist and the reference is absent.
5. **A future execution intent could carry arbitrary nested keys.** A non-null
   intent is limited to operation, target, and justification. The effective
   grant remains outside the record, and Explain/Guide still require null.
6. **Native conformance could drift into a second schema.** Python emits the
   sole checked-in fixture. The .NET probe consumes that exact file and does
   not generate or own a competing contract definition.
7. **The initial implementation left the session transition table implicit and
   omitted request deadlines.** The complete normal cycle and orthogonal
   recovery states now use a closed event table. Tutor requests carry a
   monotonic deadline that may not be elapsed or exceed the host grant.
8. **The grant view was only an internal dictionary.** A strict
   `fleet.tutor.session_grant_view.v1` record now binds existing authority,
   validity, destinations, source scope, policy references, consent, and
   cancellation generation without creating authority.

## Security assessment

- Strict JSON rejects duplicate keys, non-finite numbers, non-object roots,
  invalid UTF-8, and input above one MiB.
- Identity includes user, tenant, and project. Session, source, capture,
  consent, geometry, cancellation, retention, artifact, and budget bindings
  are checked at their owning boundary.
- Unknown capabilities and versions refuse. Validation does not issue a grant.
- An old cancellation generation fails before early stages and suppresses
  provider/render/handoff/action results at later stages.

## Correctness assessment

- Required and optional fields are explicit; unknown keys and null-required
  values refuse.
- UTC audit time and monotonic expiry are separate.
- Assistance classifications state eligibility only. No validator creates a
  score, passing state, mastery claim, or independent-learning claim.
- Missing optional modalities produce an explicit limited scope rather than a
  fabricated observation.

## Performance assessment

- The decoder checks encoded length before JSON allocation.
- Record limits bound questions, answers, claims, annotations, identifiers,
  lists, and labels.
- Validation is in-memory and linear in a bounded record. It performs no I/O,
  network request, model request, capture, render, or grant mutation.

## Maintainability assessment

- `PROTOCOL.md` documents the executable vocabulary and refusal dictionary.
- The checked-in fixture must equal `fixture_bytes()` byte-for-byte.
- The focused test maps original T005-T010 and additive X002A/X002B to visible
  assertions. The stale-consent check has a mutation witness.

## Evidence boundary

This review can approve SC-0B's source and local contract scope after a clean
suite. It does not qualify native capture, a production local transport, a
provider call, a signed installer, deployment, learning efficacy, or release.
