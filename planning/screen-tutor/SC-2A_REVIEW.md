# SC-2A grounding and overlay-contract review

**Scope:** coordinate transforms, semantic-first grounding, qualified visual
fallback boundary, inert primitive validation, revision-bound scheduling,
native contract parity and overlay-evidence exclusion.  
**Review dimensions:** security, correctness, performance, maintainability.  
**Current verdict:** locally verified and reviewed with partial native synthetic
evidence; real-app accuracy and production overlay rendering remain open.

## Resolved findings

1. **Model coordinates could be treated as screen coordinates.** One validated
   transform now includes the source extent, crop, resize, desktop origin and
   native DPI scale in both directions.
2. **Window movement could leave a convincing stale pointer.** Every ticket is
   bound to observation, source/version, capture epoch, geometry revision and
   mode; any mismatch suppresses every primitive.
3. **Duplicate controls could trigger a guess.** Equally matching semantic or
   visual candidates abstain. A unique accessibility target is preferred.
4. **A visual detector could acquire authority by configuration alone.** Visual
   fallback requires an explicit qualified-adapter state, high confidence and
   adequate target size; tiny targets request a bounded crop.
5. **Overlay data could carry active content.** Python and native parsers accept
   only four primitive kinds and exact bounded fields. Scripts, unknown fields,
   wrong types, mismatched targets and non-finite values refuse.
6. **An overlay could intercept user input.** Tickets are created with no input
   privileges and hit testing disabled. The render boundary suppresses any
   ticket that violates either property.
7. **Companion graphics could contaminate the next observation.** Overlay layer
   IDs and overlay-origin candidates are excluded from application evidence and
   grounding.
8. **Host and native math could drift.** Python and .NET tests use the same
   negative-origin, cropped, resized, 150 percent DPI fixture and exact expected
   midpoint and round trip.
9. **A malformed primitive could leak framework exceptions.** Native JSON parse
   and type failures are converted into the bounded invalid-data contract.
10. **The stale-revision test could be decorative.** Removing the geometry
    comparison makes the focused test fail; the mutation is caught.

## Security assessment

- Primitive records contain no script, URI, callback, tool request or input
  operation. Exact schemas reject duplicate and unknown fields.
- Identifiers, candidate counts, primitive counts, labels, styles, coordinates,
  model bounds and lifetimes are bounded.
- The selected application source remains authoritative. Overlay-origin targets
  cannot recursively teach from the tutor's own graphics.
- Guide remains instructional: this packet adds no click, key, invoke or value
  operation.

## Correctness assessment

- T027 passes in Python and native code for a cropped 2560 by 1440 source on a
  negative-origin desktop at 150 percent scale.
- T028 and T031 pass in both contracts. T029, T030 and T032 pass as deterministic
  offline mechanism tests.
- The native project builds under the pinned .NET SDK 10.0.401 with zero warnings
  and zero errors and still captures the real test-owned Windows fixture.
- Real application-family pointer precision, ambiguous responsive layouts,
  mixed-DPI monitor transitions and actual overlay exclusion from capture are
  not yet measured.

## Performance assessment

- Candidate selection is bounded to 64 records and overlay tickets to 16
  primitives with a 30-second maximum lifetime.
- Mapping and render checks are linear in the bounded primitive count and do not
  call a model, network, process or application-input API.

## Maintainability assessment

- `tutor_grounding.py` is the host policy and transform boundary.
- `CoordinateMap.cs` and `OverlayRenderer.cs` isolate native math and scheduling
  from capture, transport and future presentation code.
- Tests are registered in the suite, evidence inventory, doctor and mutation
  harness. Native build products remain disposable and excluded from packages.

## Evidence boundary

SC-2A is not accepted as a complete packet. The current evidence proves local
contracts and a partial native synthetic path. `OverlayRenderer` currently
validates and releases inert render-ready primitives; it does not draw a visible
production overlay. T029/T030/T032 have no native application-family witness,
and no frozen visual-grounding benchmark is qualified. No real-app pointer
accuracy, accessibility, usability, deployment, release, learning efficacy or
market-superiority claim follows.
