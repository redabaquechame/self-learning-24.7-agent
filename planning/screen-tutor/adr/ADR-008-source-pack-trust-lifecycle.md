# ADR-008: Organization-bound source and teaching-pack trust

**Status:** Accepted for implementation  
**Decision date:** 2026-09-15

## Context

Screen Tutor needs exact application guidance without treating retrieved text,
generated examples, an author label, or a passing fixture as reviewed teaching
material. Sources can also carry tenant, license, version and final-assessment
boundaries that ordinary search must not erase.

## Decision

Store immutable source revisions whose excerpts repeat their tenant, project,
license, permitted range and purpose bindings. Keep final-assessment content on
a verifier-only path that compares digests and never returns text.

Validate each immutable teaching-pack digest before review. Require conceptual
and procedural objectives, an acyclic prerequisite graph, exact source links,
misconceptions, multiple valid methods, safe practice data and independently
recomputed sample results. Keep fixture review at `CANDIDATE`. Require a distinct
active organization reviewer identity for subject-matter review and bind review
and qualification records to the exact digest. Only a qualified digest can be
assigned or retrieved as exact teaching guidance.

## Failure criteria

- Retrieval crosses tenant/project scope, exceeds source rights or returns final
  assessment text.
- An unsupported application version receives an exact route claim.
- A cyclic, unverified or incorrectly scored pack reaches review or assignment.
- The author, a fixture, an unbound human label or a stale digest authorizes a
  production teaching pack.
- Assignment status implies that a learner succeeded or retained knowledge.

## Reversal

Disable pack assignment and exact tutor retrieval. Keep the immutable source and
review records for audit, and fall back to a labelled missing/unqualified-source
response without deleting final-assessment separation or learner history.
