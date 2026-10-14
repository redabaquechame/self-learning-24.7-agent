# Human submission verification core implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. One fresh whole-package review, no per-task implementers or reviewers.

**Goal:** Connect immutable actual submitted bytes to verification-only human assessment through the existing sealed learning.v1 service, without agent pursuit or repair and without turning unknown exposure into independent success.

**Architecture:** Add an optional host-owned assessment authority using two focused modules: tutor_attempts.py owns scoped immutable artifact custody and submission lineage; tutor_assessment.py owns closed deterministic predicates and exposure/qualification decisions. LearningService optionally consumes this authority; its default feature-off/legacy digest-only submissions remain unscored. Host installation/ingestion is distinct from a frontend request. No request can choose an evaluator, answer key, expected result, qualification or score. Production assignment requires current exact independently reviewed pack/rubric authority; local synthetic mechanical checks remain visibly unqualified.

**Tech Stack:** Existing Python3.12 stdlib, shared LearningService and File/Control Authority. Closed canonical JSON/group-sum predicates only in this first core package; no code execution, archive extraction, provider, network or package installation.

**Spec:** Original SC-2F and X034A/B,Y005–Y008 in ../planning/screen-tutor-v2-2026-09-14/execution/WORK_PACKAGES.md; specs/SHARED_LEARNING_AND_ASSESSMENT.md sections2/3; technical boundary ownership. mastery._execute_task still calls goalmod.pursue then contract.verify and remains the legacy agent-evaluation path. This package must not call it.

## Global constraints and scope rulings

- Preserve every authored dirty change, immutable baseline and existing agent evaluation. No broad staging, commits, push or deployment.
- A submission snapshot is immutable exact bytes with tenant/project/learner/attempt/course/variant/rubric scope and a host ingestion receipt. Missing/tampered/wrong-scope/partial uploads refuse; a frontend digest alone is not custody proof.
- Store submissions in owner-controlled org state, reject redirected paths, bound input bytes and JSON depth/count, reject archives/executable formats/duplicate keys/nonfinite data. No student file is rewritten during grading.
- Exposure coverage is explicitly COMPLETE/UNKNOWN; accommodations are independent of answer exposure. Agent/shared/help/exposure disqualify independence; incomplete telemetry never establishes independence. No diagnosis/mastery percentage or unseen-world claim.
- A qualified rubric is host-installed against current reviewed immutable source/pack authority; neither model nor learner can supply or approve it. Local mechanical fixture results remain unqualified, not assignment acceptance.
- Separate logical predicate observations from final learning/qualification status. Unknown/unsupported subjective/code/spreadsheet evaluators return review/unavailable; never fabricate a pass.
- Dependencies SC-2B/2C/7A remain unaccepted. Ruling: implement their independent verification-only core boundary now, keep content/native/human and complete evaluator-family qualification open, and continue other eligible work. Cost if wrong: local proof cannot satisfy original packet acceptance.
- Current native/onboarding deadline campaign is frozen. Do not install this plan or edit product/tests until the combined run and revision52 receipt are complete.

## Review focus

1. Incorrect submitted bytes remain incorrect; instrument pursuit/autofix/artifact writes and assert zero grading-side calls in success/failure/retry paths.
2. Tenant/project/principal/attempt/course/variant/rubric and ingestion custody survive submission/evaluation; forgery, overwrite, malicious/partial upload and caller-selected grader/expected answer refuse.
3. Concurrent/repeated evaluation creates one verdict lineage per immutable submission; evaluator error preserves the same original bytes for retry. Late/double submission cannot erase an earlier attempt.
4. Answer exposure, shared/agent help, repeated/example input and UNKNOWN telemetry do not create independent credit; allowed accommodations do not automatically disqualify.
5. Optional learning.v1 integration preserves legacy default behavior and every surface uses the same authoritative result; client mutations cannot create grading or qualification authority.
6. Appeals/corrections supersede derived judgment and retain original evidence; deletion/export respect retention scope and actual readback rather than return unsupported success. Unimplemented deletion remains explicit instead of pretending completion.

## Task1: Immutable custody and verification-only mechanical core

Files: new tutor_attempts.py, tutor_assessment.py, tests/test_tutor_human_assessment.py and bounded synthetic evaluation/tutor/submission_fixtures manifest/files.

Frozen interfaces for this core:

- `AttemptCustody(home, *, project_id, key)` uses a host-supplied>=32-byte custody key and owner-controlled org/tutor-human-submissions directory. `begin(attempt_id, scope, rubric_binding)` seals tenant/project/learner/course/variant/rubric identity; `ingest(attempt_id, scope, payload: bytes, mime='application/json') -> receipt` bounds256KiB; `submit(submission_id, attempt_id, scope, artifact_digests) -> immutable metadata`; `read_submission(submission_id, scope) -> tuple[metadata, exact bytes]` rechecks seals/digests. No upload token or client-selected path, no derived score, no key on disk.
- `ReviewedRubric.from_pack(home, pack_id, *, assessment_ref)` checks tutor_packs.status, exact current pack digest and hidden source-manifest reference via existing tutor_sources authority; expected results come from that exact hidden source, never the frontend. Support only closed JSON_EQUALS/GROUP_SUM records; unsupported families refuse. `ReviewedRubric.local_check(spec)` creates a permanently LOCAL_ONLY record for owned mechanical witnesses; it cannot produce a qualified passing result or learning credit.
- `HumanAssessmentAuthority(custody)` owns explicitly host-installed `authorize_assignment(assignment_id, learner_id, tenant_id, course_revision, variant_revision, rubric, *, exposure_reader)` bindings. Each current exposure reader is host-injected and supplies closed `{coverage, actor, assistance, answer_exposed, repeated_example, accommodation_allowed}` facts; missing/invalid coverage is UNKNOWN or refused, never independent by default. It owns `begin(attempt, binding)`, `ingest(attempt_id, binding, bytes)`, `submit(submission, binding)`, `evaluate(submission_id, binding)` and immutable verdict caching. A scoped non-mechanical/local result contains observed predicate result but passing=None and independent_success=False.
- `LearningService(..., human_assessment=None)` accepts only the typed host backend. `ingest_human_artifact(binding, attempt_id, bytes)` is authenticated host ingress, not a generic client path/API. Existing attempt.begin/attempt.submit call that backend only when configured; `assessment.evaluate` accepts only `{submission_id}` and its optional backend availability is per service, leaving the default reserved behavior intact. Host identities/course/assignment are read from sealed records. All four LearningAdapters call this same service and receive the same verdict lineage.
- Public verdicts expose identity/digests/predicate observations/qualification/attribution; they expose no hidden expected answers or host key. Existing scoped record visibility applies; additionally require same learner or explicit `assessment:evaluate:any`/`learning:read:any` host entitlement for foreign-learner evaluation/readback.

Ruling: custody keys are supplied by the host; this package does not persist a secret or claim cross-restart key provisioning. Production installation/recovery must own that step. A locally checked synthetic rubric never masquerades as reviewed final content, even when its predicate passes. A request containing actor/expected/pass/qualification/evaluator fields is refused rather than interpreted as grading authority.

Ruling: an observed negative showed that a later clean current snapshot could erase earlier known answer exposure. Initial facts are now sealed with the immutable attempt and subsequent distinct facts use a bounded signed append-only chain; host publication has an explicit `record_human_exposure` hook. A second observed negative showed a valid-prefix truncation; the current custody instance anchors its chain head. Unknown coverage and known assistance only accumulate. Cross-restart head recovery/anti-rollback and durable verdict projection remain explicit prerequisites, not claimed by this in-process core. The host must record help before publication and use UNKNOWN when it cannot attest complete recorded coverage.

- [ ] Pin current source/HEAD and legacy grading call boundary; record module responsibilities/interfaces in ledger before edits.
- [ ] Write observed absence RED for actual wrong/right submitted JSON, immutable input digest, no-pursuit/no-repair, bad upload/tamper/scope/exposure and exact retry/concurrency.
- [ ] Implement bounded host-ingested custody and immutable submissions with exact scope; new attempts receive authority before artifact ingestion.
- [ ] Implement closed JSON equality and group-sum verification with semantic numeric checks and method-independent output; no answer key or generated replacement in public verdict.
- [ ] Implement explicit UNKNOWN/assisted/accommodation attribution and mechanical-versus-qualified distinction; keep production rubric/pack authority mandatory.
- [ ] Run focused RED/GREEN, selective no-op/tamper/pursuit negatives and artifact readback; retain every setup/product failure.

## Task2: Shared learning service integration and current review

Files: modify learning_contracts.py, tests/test_learning_surface_parity.py as necessary and tests/run_all.py; add exact scope/qualification design record under planning/screen-tutor.

Ruling: affected package verification reproduced an unclassified new registered test. Add its name to the existing Tutor/learner mechanism group in evidence.py, preserving one-system accounting; pre-edit bytes/hash were pinned before that additive registry change. This is required packaging/evidence integration, with no original protected-file exception. Numerical verification is explicitly bounded to magnitude10^12 and8 decimal places so closed group arithmetic stays exact; unsupported precision refuses instead of returning a rounded grade.

- [ ] Write watched RED for optional sealed service attempt/ingest/submit/evaluate routing, foreign principal/tenant/project, forged host/score/expected result and unchanged default digest-only behavior.
- [ ] Integrate only the host-owned typed backend. Bind actual snapshot/receipt before a submitted state; reserved assessment availability is conditional on configured backend and required host entitlement, never a frontend flag.
- [ ] Exercise actual immutable submission and verdict through main/native/standalone/embed adapters, idempotent retry and concurrent assessor; preserve old mastery tests and instrument actual pursuit/write boundaries.
- [ ] Obtain one fresh read-only package review against pinned sources/spec/RED/GREEN. Repair Critical/Important once with observed RED/GREEN plus green focused suite; ledger Minor and every declined behavior.
- [ ] Freeze reviewed final candidate and run affected full offline regression once. Record source/log/artifact hashes, skipped/native/content/provider tiers and unaccepted packet state; continue the complete both-product platform.

Remaining original SC-2F implementation/qualification beyond this core: authorized native upload/submission UX, real spreadsheet/formula and isolated code verifier adapters, reviewed writing/roleplay rubrics, institution/human exposure policy, appeals/correction/export/deletion lifecycle and installed end-to-end qualification. They remain mandatory; this plan does not silently redefine the packet as complete.
