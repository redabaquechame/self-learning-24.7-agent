# ADR-011: declarative canvas and disposable practice copies

**Status:** Accepted for implementation  
**Decision date:** 2026-09-15

## Context

Screen Tutor needs to explain concepts visually and let a learner try a task
without turning model output into executable UI content or modifying the
learner's real project. A renamed answer is also insufficient evidence of
transfer, and assistance must remain visible in later learner evidence.

## Decision

1. The explanatory canvas accepts only `tutor.scene/1`, a closed declarative
   schema containing text, axes, equations, graph samples, nodes, edges and
   bounded sliders. Expressions use a small arithmetic tree. No script, URI,
   callback, markup or tool request is valid scene content.
2. Python deterministically evaluates every graph sample against its equation.
   Slider changes recompute affected graph values. The native WPF control
   consumes the generated `tutor.canvas-render/1` fixture and independently
   rechecks schema, relationships and equation results before drawing.
3. Practice accepts only a synthetic or explicitly licensed practice source.
   Production documents are declined. File Authority reads the exact digest
   and writes only an internally derived path below
   `artifacts/tutor-practice/`.
4. Reset verifies all declared watched-source digests, rereads the original
   source by exact digest, and writes only the generated practice artifact.
   Stop clears disposable state. The current packet exposes no command,
   process, network or application-input route, so Execution Authority is not
   invoked. Any later external transformation must use `execution.run`.
5. Worked, partial and independent variants carry explicit reveal and
   assistance accounting. A filename-only copy is ineligible for transfer.
   Every generated variant remains a candidate until its mechanical and
   review gates pass.
6. Mechanical JSON comparison can establish artifact equality only. Creative
   or subjective criteria return `HUMAN_SUBJECTIVE` and require human review.
   Neither result establishes learning or retention.

## Failure criteria

- Reject a scene if its schema, expression tree, graph samples, relationships,
  primitive bounds or text alternative do not verify exactly.
- Reject practice creation, verification or reset if source rights, lineage,
  content digest, expected-result digest or derived destination differs from
  the frozen session record.
- Refuse any claim of independent transfer, learning, retention, native-app
  safety or release readiness without its separate qualifying evidence.

## Consequences

- The native canvas can render validated concepts and hold mouse ink without a
  source-document handle. Reset and Stop are local and immediate.
- Source writes cannot be redirected by altering the returned artifact path;
  the path is recomputed from the session identities before every operation.
- The source receipt and expected-result lineage still need to be supplied by
  the qualified pack/host integration. The current contract cannot qualify a
  caller's self-asserted rights metadata.
- Native T045 currently uses a test-owned WPF canvas and a bound digest. It is
  not a human interaction run against a supported production application.

## Reversal

Disable canvas and practice entry points, withdraw affected candidate
practice versions, and invalidate their derived learner judgments. Preserve
the original artifacts and append-only evidence history.
