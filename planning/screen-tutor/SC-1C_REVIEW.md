# SC-1C source and teaching-pack review

**Scope:** tenant/project-bound source records, permitted excerpt ranges, app
version qualification, pack graph and sample validation, hidden assessment
separation, review authority, qualification, assignment and retrieval.  
**Review dimensions:** security, correctness, performance, maintainability.  
**Current verdict:** locally verified and reviewed; the bundled reporting pack
remains a candidate until a real independent subject-matter reviewer approves it.

## Resolved findings

1. **A source result could cross a tenant or project boundary.** Every stored
   excerpt repeats and validates its tenant, project, revision, license and
   purpose binding. Retrieval walks only the caller's exact registry scope.
2. **Unlicensed material could enter a pack.** Registration requires permitted
   rights and rejects excerpts outside declared ranges. Pack validation resolves
   each exact source/revision/excerpt reference before review.
3. **A final assessment could leak through ordinary tutor retrieval.** Hidden
   records are never returned by search or direct reads. The assessment verifier
   compares a digest and returns no content.
4. **A stale app route could look exact.** Source and pack version ranges use
   strict semantic versions. Out-of-range routes return a named scope limit and
   no claims.
5. **An invalid curriculum could become assignable.** Pack validation rejects
   prerequisite cycles, missing conceptual or procedural objectives, unlinked
   sources, absent misconceptions, fewer than two valid methods, unsafe samples,
   and expected results that differ from independent recomputation.
6. **A fixture, author or unbound human label could approve production content.**
   Author self-review is refused. Human review requires an active organization
   identity with reviewer permission. Fixture review proves the validation
   mechanism but leaves the pack in `CANDIDATE`; only an authorized independent
   subject-matter review can reach `REVIEWED`.
7. **Review could silently apply to changed bytes.** Reviews and qualification
   records bind the immutable pack digest. Qualification cannot promote a changed
   or unreviewed pack.
8. **A qualified pack could imply learner success.** Assignment manifests state
   `learner_success_claimed: false`; learning efficacy requires separate human
   evaluation.

## Security assessment

- Registry and pack identifiers are bounded and traversal-safe; symlinks and
  unexpected pack files are refused.
- Source records and pack files have explicit byte/count/character ceilings.
- Tenant/project ACLs, rights, source revision and purpose are checked at the
  record, pack and retrieval boundaries.
- Assessment text has no tutor-readable API. The verifier exposes only whether a
  caller-supplied digest matches.

## Correctness assessment

- The reporting fixture contains conceptual and procedural objectives, an
  acyclic skill graph, two valid solution methods, misconceptions, licensed safe
  practice data and an independently recomputed expected result.
- T022 through T026 pass for ACL isolation, cycles, app-version refusal, sealed
  assessment denial and incorrect expected results.
- Synthetic authority records exercise the state machine only. They do not
  represent a real content review.

## Performance assessment

- Retrieval has explicit record, result and character bounds and deterministic
  ordering.
- Validation and lookup use local immutable files; no network or model request is
  needed to decide trust or version eligibility.

## Maintainability assessment

- `tutor_sources.py` owns source provenance and retrieval; `tutor_packs.py` owns
  curriculum validation, review and assignment. Their trust transitions are
  explicit and append-only.
- The synthetic pack uses five schema-specific JSON files so source references,
  examples, practice and hidden assessment metadata remain separately reviewable.
- Tests are registered in the authoritative suite, evidence inventory and
  mutation harness.

## Evidence boundary

SC-1C has verdict `LOCAL_VERIFIED_REVIEWED_FIXTURE_SUBJECT_REVIEW_BLOCKED`.
The implementation and synthetic candidate are locally verified. The candidate
is deliberately unassignable because no real independent subject-matter reviewer
has approved its accuracy, pedagogy, rights and version coverage. No content,
human-learning, deployment, release, accessibility or market-superiority claim
follows from this review.
