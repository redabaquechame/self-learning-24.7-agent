# Authenticated visible teaching canvas implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. One fresh whole-package review, no per-task implementer agents.

**Goal:** Deliver an actual source-bound teaching scene in the companion's Ask journey, with isolated practice ink, current-source clearing and a readable text alternative.

**Architecture:** Add a host-owned immutable `TeachingScene` boundary over the existing closed declarative scene validator. The authenticated ANSWER optionally carries a bounded presentation receipt. Native transport validates it, then the actual SessionWindow renders it through TeachingCanvas under the same source/content/generation checks as its answer. Existing plain answers remain unchanged.

**Tech Stack:** Python3.12 stdlib, existing signed bridge and pack/source registry, .NET10 Windows/WPF and existing TeachingCanvas. No added dependency, model/device/private-source call or OS-input grant.

**Spec:** Original `../planning/screen-tutor-v2-2026-09-14/execution/WORK_PACKAGES.md` SC-2C and SC-2D; `specs/TECHNICAL_CONTRACTS.md` InstructionPlan, geometry and session interruption; `specs/TUTORING_AND_PACKS.md` declarative canvas and safe practice; existing `tutor_canvas.py` and TeachingCanvas closed schemas. T041/T043 local mechanisms advance; T045 and all content/native/human acceptance remain open.

## Global constraints and rulings

- Do not install or edit production/test/plan/metadata until revision54 normal is terminal and its exact source archive/receipt is saved.
- Preserve all authored dirty changes, original immutable locks and existing grading. No blanket staging, commit, push or deployment. Ruling: source ownership/selective commit stays open; preserve exact source archives in lieu of claiming a clean reviewed commit.
- Local scene installation is permanently labelled LOCAL_ONLY, visibly a demonstration, never learning or production content qualification. Reviewed installation requires current assignable independently reviewed pack, exact visible teaching excerpt/reference membership and loaded-byte digest. Hidden assessment data never enters a scene.
- A scene is explanatory data, never script/HTML/code/tool/input authority. No guessed desktop origin or desktop overlay is introduced; that original work remains open.
- At most64 scene primitives, closed existing expression/sample limits,256KiB source excerpt/scene input and bounded signed message apply. Exact tenant/project and request/source/observation/revision/epoch/geometry/content digest bind every receipt. Expiry cannot outlive request, observation or current grant.
- Existing default feature-off/import paths perform no new IO or process launch. Unsupported scene, scope or current authority yields explicit unavailable presentation; no substitute source, local qualification promotion or assessment pass.
- Dependency SC-1C/2B/2C acceptance remains open. Ruling: install independent mechanical/visible integration now using explicitly labelled owned fixtures, while real reviewed content/assignment/practice/human/provider/installed qualification remains mandatory.

## Review focus

1. A client-supplied scene/reference/qualification must not create teaching authority or expose final-assessment content (Task1).
2. Same-tenant foreign project, pack/source replacement or delayed source/Stop/expiry change must not release or display a stale scene (Tasks1–3).
3. Authenticated malformed/oversized/duplicate/unknown scene data must not crash the UI or silently render a different scene (Task2/3).
4. Practice ink/reset/Stop must not write source files or retain source content/text alternatives after clearing (Task3).
5. Plain-answer callers, source selection/Ask interruptions, feature-off, minimum-window scrolling and accessible text/keyboard recovery must keep working (Tasks2–4).

## Task1: Host-owned immutable teaching scene and source bindings

Files: create `tutor_presentation.py`, `tests/test_tutor_presentation.py`; use existing tutor_canvas/tutor_contracts/tutor_packs/tutor_sources.

Interfaces: `TeachingScene.local_check(scene, *, tenant_id, project_id)` creates immutable LOCAL_ONLY data; `TeachingScene.from_pack(home, pack_id, *, reference)` loads the exact visible reviewed teaching excerpt containing a closed scene; `TeachingScene.render(request, observation, current_owner) -> presentation` uses current authority and closed render model; `TeachingScene.verify_current()` checks exact bound data/reference/qualification. `PresentationRefused` carries secret-free unavailability. Constructor refuses arbitrary direct installation. Public receipt schema `fleet.tutor.presentation.v1`: schema, binding, expires_at_monotonic_ms, qualification, render_model, learning_success_claimed(False). Binding fields: request_id/session_id/user_id/tenant_id/project_id/observation_id/source_id/source_revision/capture_epoch/geometry_revision/content_sha256/consent_revision/cancellation_generation. Supported intent LEARN, modes EXPLAIN/GUIDE only. Qualification describes source provenance; it does not establish concept correctness, app-transfer or learning effectiveness.

- [ ] Pin HEAD/base hashes and responsibilities before production edits; carry existing observed draft absence RED into this package with exact provenance.
- [ ] Install draft test as normal acceptance script; test current admitted source→closed render model, exact binding/finite expiry, unqualified local label, unchanged inputs, foreign scope and delegation/assessment refusal. Run Python script: expected missing-module RED already observed; keep log.
- [ ] Implement scoped immutable factory, current checks and render through `validate_scene/start_scene/render_scene`. Write actual RED/GREEN for mutation/qualification promotion, hidden excerpt, reference not in pack, actual loaded-byte mismatch and revoked/replaced source/pack.
- [ ] Run `tests/test_tutor_presentation.py` plus canvas/packs/sources tests. Expected PASS, no real reviewer qualification claim from synthetic temporary-role fixture.

## Task2: Optional authenticated scene delivery

Files: modify tutor_host.py/tutor_transport.py, companion BridgeCodec.cs/BridgePayloads.cs/NativeHostClient.cs; transport/host/native contract tests and closed fixtures.

Interfaces: optional typed `NativeTutorHost(..., presentation=None)`; existing ANSWER `{instruction}` unchanged without backend, optional `{instruction,presentation}` only after checked host scene rendering. Before send, recheck current scene/source/owner under release checks. Python/native codec allows only that optional field with exact closed receipt. `NativeHostClient.SendTeachingQuestionAsync(...) -> TutorAnswer(Instruction, Presentation?)`; existing SendQuestionAsync delegates and returns Instruction for compatibility. Native receipt is checked against original observation/request/current capture before publication. Exact current pinned executable/host pair is required; this local additive bridge change does not qualify old installed clients or claim a released protocol migration.

- [ ] Observe RED for real optional scene wire, altered receipt authentication, binding mismatch/expiry, and absent native typed answer. Preserve original plain-answer fixtures byte-compatible.
- [ ] Implement structural semantic closed render validation without constructing WPF controls on the receiver thread. Scene parse/content errors refuse presentation; current answer-only capability remains truthful.
- [ ] Run transport/host/connection/contracts/feature-off and full native contract checks. Expected PASS; source/owner/Stop change during resolution or before send suppresses release, zero added provider/tool/input calls.

## Task3: Actual visible companion canvas and isolated ink

Files: SessionWindow.xaml/.cs, TeachingCanvas.cs if needed for complete clearing, new native `TeachingPresentationJourneyTests.cs`, native test registration and actual owned-host fixture branch.

Interfaces: SessionWindow consumes TutorAnswer under existing source/frame/guidance guards; owned canvas host creates/disposes TeachingCanvas and a readable text alternative. Reset clears companion ink only. ClearAnswer also disposes scene/ink/text alternative; finite expiry uses current monotonic time. Ask with no scene hides canvas without inventing demonstration content. No named source application/document is mutated.

- [ ] Actual owned WPF+Python pipe RED: LEARN Ask returns configured closed scene, expected diagram/text alternative visible; source bytes unchanged. Include Pause/Stop/replace/current-frame/revocation/expiry while pending, invalid scene, old answer-only path, source content text clearing and reset/keyboard/minimum-window cases.
- [ ] Implement visible labelled scene, text alternative, bounded layout and disposable input lifecycle. A cleared scene is not reusable; fresh current receipt creates a new control. A practice stroke is not assessment or app task success.
- [ ] Run complete native checks and correctly selected actual host campaign with only owned forms/local injected answers. Expected PASS; no private picker, real provider/device/learner/subject reviewer/install qualification.

## Task4: Register, review, freeze, preserve and continue

Files: tests/run_all.py/evidence.py, execution receipt/state/checkpoint and comparison generator outside build.

- [ ] Register real presentation test in both suite and central system classification; affected package checks PASS with185 test accounting.
- [ ] One fresh whole-package read-only review of exact pinned candidate/base sources and Review focus; root repairs Important/Critical findings once via observed RED/GREEN. No second review.
- [ ] Freeze final source, run full normal once, verify one terminal record and unchanged files; preserve actual native/host artifact hashes, every failed/skipped case and every frozen source byte.
- [ ] Record partial/unaccepted SC-2C/2D receipt and current comparison. Continue production owner/provider/Fleet discovery, genuine source geometry/desktop overlay, actual qualified assignment/practice and every original retained packet. Neither product becomes handover-ready from this package.
