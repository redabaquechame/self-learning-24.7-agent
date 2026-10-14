# Native human practice implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Continue all both-product work after this package; one fresh whole-package review, no per-task delegation.

**Goal:** Connect a host-assigned practice attempt, actual learner artifact bytes,
submission and truthful review status to the native companion and shared learning
records without turning agent help or a digest-only claim into independent credit.

**Architecture:** Reuse LearningService, sealed HostBinding, AttemptCustody and
HumanAssessmentAuthority. The host configures assignment, exact variant and
reviewed rubric; native/browser content selects none of those authorities.
Uploaded bytes enter existing bounded immutable custody. Publication of assistance
must enter shared exposure before the answer is released. Source-only explanations
retain their current unqualified behavior when practice is not configured.

**Tech Stack:** Existing Python learning.v1 and authenticated Windows companion.
**Spec:** Original SC-2F and SC-7A in planning/screen-tutor-v2-2026-09-14;
specs/TECHNICAL_CONTRACTS.md and prior SC-2F-human-core-review-r53.md.

## Global constraints

- Actual submitted bytes, never frontend digests alone; MAX_ARTIFACT_BYTES256KiB,
  MAX_ARTIFACTS8, existing closed JSON predicates only until other graders exist.
- Preserve exact project/learner/course/variant/rubric and sealed binding.
  Current HostBinding has no project field; do not infer project from a body.
- HumanAssessmentAuthority currently owns one project's custody. Resolve shared
  multi-project service authority before enabling practice across installations.
- No agent execution or artifact repair during grading; no independent success
  for local-only content, unknown exposure, agent/shared work or answer reveals.
- Native transport1.1 currently has no upload/practice messages. A change requires
  explicit closed schema/version negotiation and Python/.NET parity tests.
- Do not add production microphone, private-source, paid-provider, installer,
  institutional or buyer acceptance from owned fixtures.
- Preserve prior immutable source receipts and protected-file exceptions.

## Tasks

1. Pin current sources and resolve shared project custody and assignment admission.
   Write RED for foreign project/learner/variant, disabled practice and digest-only
   submission. Implement typed host-configured practice ownership; run existing
   human-assessment and four-surface parity checks. Expected: exact byte receipts,
   one canonical submission, no grader/reference leakage or false credit.
2. Add negotiated native practice messages and client methods with closed bounded
   fields. RED for unknown fields, body-chosen identity/rubric/project, oversized
   upload, stale binding, cancellation and source-only role. Expected: refusals
   before custody mutation and Python/.NET parity with unchanged1.1 source paths.
3. Add native assignment/start/upload/submit/status controls. Use explicit selected
   learner files, no generated replacement. Track answer/help exposure before
   release and read the same shared result from another authorized surface.
   Expected: actual owned wrong/right bytes distinguish predicate result, while
   local/unknown/assisted receipts cannot claim independent learning success.
4. One fresh review, one root Important/Critical RED/GREEN repair pass, frozen
   registered/source/native verification, honest state/report update. Continue
   the remaining original Fleet/Tutor packets without accepting SC-2F from this
   bounded mechanical integration.

## Review focus

- Multi-expert/project and principal isolation with one runtime learning service.
- Uploaded JSON remains exact bytes and never selects grader/expected answer.
- Assistance reaches shared exposure before native publication; late help revokes
  derived current credit without erasing original history.
- Cancel/Stop/role/configuration change cannot publish a stale upload or outcome.
- UI failures/retries preserve learner work and do not claim submitted or passing
  before the shared service confirms it; unavailable practice stays explicit.
