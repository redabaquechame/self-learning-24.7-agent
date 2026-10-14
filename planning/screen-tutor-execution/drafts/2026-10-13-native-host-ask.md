# Authenticated native host and Ask implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the real companion selection, host authorization, bounded frame transport and Ask response to the existing Fleet tutor service.

**Architecture:** The Windows native process owns capture and its per-user pipe; the existing Python host owns identity, current grants, provider dispatch and learner evidence. A new optional adapter connects those existing boundaries, with a per-launch inherited secret bootstrap, mutual typed handshake, exact selection/epoch binding, one-shot frame memory and validated answer presentation. Neither adapter nor pipe is an authority or a new general orchestrator.

**Tech Stack:** CPython3.12.13 standard library/optional Windows ctypes, existing WPF .NET SDK10.0.401 and Windows App SDK2.4.0, existing named-pipe/CaptureSession/TutorSession/TutorService/model gateway/learning.v1 modules.

**Spec:** Original `../planning/screen-tutor-v2-2026-09-14/execution/WORK_PACKAGES.md`, SC-1A additive instructions1–7 and SC-2D; `planning/screen-tutor/adr/ADR-002-local-transport.md`, ADR007, ADR010, ADR013; `planning/screen-tutor-execution/evidence/SC-2D-native-integration-readiness-r24.md` records current gaps. This is a dependent implementation package within the existing whole-platform goal. It does not replace genuine overlays, teaching/assessment, accessibility, installed novice, real-provider/content/human or buyer-release requirements.

## Global constraints

- Wait for native-continuity FINAL_CAMPAIGN to be terminal before adding/changing candidate source. Preserve its exact verdict and every skip/failure.
- Preserve the twelve protected source files and pre-existing authored dirty work. The first host adapter is optional and host-injected; default imports/feature-off do not spawn, connect, capture, query UIA, call a provider or write learner success. Reviewed main dashboard/CLI discovery integration follows without silently changing baseline locks.
- The per-launch secret is 256 bits, ephemeral, and transferred through a bounded inherited anonymous channel. Never put it in command arguments, environment dumps, files, diagnostics or model input. No new TCP listener.
- Named-pipe maximum declared JSON payload is 1 MiB, strict duplicate-free typed records, bounded nesting, monotonic sequence and deadlines, correlation and cancellation. Pixel transfer is opaque one-shot memory, not JSON/base64/logs/durable messages.
- CaptureSession bounds remain3 frames,32 MiB/frame,64 MiB/buffer and15-minute maximum capture authorization. Host grants remain current, finite and source-exact; OS selection and host authorization both precede pixels.
- No private source, paid provider, real-app input, model upgrade, cloud action or release during local implementation tests. Real-boundary witnesses use only test-owned windows and controlled fixture responses; they prove plumbing, not useful real-model work or independent learning.
- Sharing Stop remains synchronous/local; no peer/model/worker may delay it. Panel close, speech Stop and unrelated Fleet task cancellation remain distinct. Source changes, loss, transport loss, pause and Stop invalidate the applicable pending observations/answers.
- Do not derive desktop origin or HWND from a picked source's title or foreground window. Actual visible overlay/source geometry is a subsequent required integration package, with its current feasibility gap retained. Text answers do not qualify that gate.

## Review focus

1. Same-user foreign/stale processes, corrupted launch input and replayed handshakes cannot attach to the current host/native session; Task2/3 tests pin these.
2. Grant revocation, identity/project change, expired deadlines and source/epoch change during slow dispatch must suppress the released answer; Task1/5 tests pin these.
3. Pipe stalls, partial frames, shared-memory reuse and peer teardown cannot hang local Stop or preserve accessible pixel buffers; Task3/4 tests pin these.
4. Selection retries/replacement cannot confuse independent host/native epochs or restore old sharing after Stop; Task1/4 tests pin these.
5. Fixture output, missing provider/accounting and a merely accepted contract cannot be presented as a qualified answer or learner success; Task1/5 tests pin these.

## File responsibilities

- `tutor_service.py`: retain current admission/validation and add current-policy response release, without changing authority or real-provider eligibility.
- `tutor_host.py` (new): optional host-owned native-session adapter, consuming current policy and the shared learning adapter; no transport, platform import or general orchestration at module load.
- `tutor_transport.py` (new): strict authenticated codec and optional Windows pipe-client/bootstrap lifecycle; no capture, identity grants or model calls.
- `companion/windows/ScreenTutor/OwnerBridge.cs`: evolve existing native transport into mutual typed bidirectional traffic; preserve negative/replay/hung-peer witnesses.
- `companion/windows/ScreenTutor/NativeHostClient.cs` (new): bootstrap/host exchange and cancellation, with typed selected-source/frame/request/answer messages.
- `companion/windows/ScreenTutor/FrameTransfer.cs` (new): owned one-shot bounded memory, BGRA-to-PNG conversion and wipe/lifetime.
- `App.xaml[.cs]`, `SessionWindow.xaml[.cs]`, `SessionViewModel.cs`: actual optional host startup, capture authorization and Ask/presentation controls; no fallback invented answer.
- `tests/test_tutor_host.py`, `tests/test_tutor_transport.py` (new), existing service/native tests and owned native test projects: RED/GREEN and real process-to-process mechanism witnesses.

## Task 1: Actual host-authorized request-to-response path

**Interfaces:** Add `TutorService.ask_current(request, current_owner_state, observations, session) -> dict`, where current_owner_state is a host-supplied callable, never payload-selected. Return `{allowed, reason_code, record_id, instruction}` only after current admission, dispatch, exact current observation/source/generation re-admission and existing instruction validation. Add `NativeTutorHost(service, current_owner_state, learning_adapter)` and methods `select_source(native_receipt) -> dict`, `ask(request, observations) -> dict`, `stop() -> None`; immutable host identity comes from the sealed learning adapter and current owner reader. Selection admits the exact native receipt/epoch and creates no grant; host response contains only the actually granted capabilities and finite source-exact authorization.

- [ ] Write `check_current_answer_release`: valid selected-source request returns the actual validated instruction; wrong identity, no observation, no configured dispatch, late revocation/expiry/cancellation/source change and forged instruction refuse with no instruction release. Assert zero independent-learning/effect-success records from answering.
- [ ] Run `python tests/test_tutor_host.py`; expected RED is absent current-policy answer route or returned validation-only verdict, not an import/setup error.
- [ ] Implement the interfaces using existing TutorService admission, contracts and learning.v1 sealed authority. Validate native receipt schema before adapting source; explicitly bind native/host capture epochs instead of ignoring mismatch. Never accept principal/tenant/provider/permission fields from native request body as authority.
- [ ] Run `python tests/test_tutor_host.py` plus `python tests/test_tutor_native_session.py`, `python tests/test_learning_surface_parity.py`, `python tests/test_tutor_investigation.py`; expected GREEN, with existing routes and feature-off unchanged.
- [ ] Record source hashes and commit only reviewed owned/dependency changes after the existing authored-work ownership ruling; never stage the whole dirty tree by default.

## Task 2: One typed authenticated bidirectional wire contract

**Interfaces:** `tutor_transport.encode_message(key, envelope) -> bytes`, `decode_message(key, raw, expected, now_ms) -> dict`. Native OwnerBridge supplies equivalent typed write/read. Exact envelope fields: `schema`, `protocol_version`, `session_id`, `bridge_epoch`, `sequence`, `message_id`, `reply_to`, `deadline_monotonic_ms`, `cancellation_generation`, `message_type`, `body`, `mac`; schema `fleet.tutor.bridge.v1`, protocol1.1. MAC covers every preceding field, with deterministic JSON bytes and shared Unicode/numeric fixtures. Message types: HELLO, HELLO_ACK, SELECT_SOURCE, CAPTURE_AUTHORIZATION, OBSERVATION, ASK, ANSWER, PAUSE, STOP, UNAVAILABLE, REFUSAL. Closed type/payload shapes and maximum1 MiB apply before dispatch. Deadlines use one documented Windows monotonic clock domain; host gateway deadlines are converted explicitly into its own clock, never compared by an assumed shared epoch.

- [ ] Write codec roundtrip/cross-language fixture tests and negatives for altered deadline/type/correlation/body, duplicate properties, Unicode, future/unsupported version, oversized/deep input, sequence gap/replay, stale epoch/cancellation and expired envelope.
- [ ] Run Python transport test and native build/run; expected RED is missing typed authenticated outbound/handshake route and/or acceptance of an altered authenticated policy field.
- [ ] Implement the shared record and signing rules through the existing OwnerBridge; bounded accepted-sequence history, serialized writes, explicit HELLO challenge and mutual protocol/session/peer proof precede operational messages. Preserve existing replay/duplicate/hung-read witnesses while upgrading their production-format envelope.
- [ ] Run Python/native tests; expected GREEN, including byte-compatible cross-process fixtures and deadline alteration refused.
- [ ] Record exact contract fixtures/digests and owned commit as in Task1.

## Task 3: Real optional per-launch host/native connection

**Interfaces:** `NativeTutorHost.launch(native_executable, *, timeout_ms) -> connection` uses a host-controlled verified executable and inherited anonymous bootstrap stream; payload is bounded to4096 bytes and never request-text-selected. Native `NativeHostClient.OpenAsync(Stream bootstrap, CancellationToken stop)` validates the bootstrap, opens the per-user native-owned pipe and completes Task2 handshake. Python Windows backend uses cancelable bounded IO and owns only its launch/pipe handles. Missing/offline/feature-off starts no process and returns explicit availability. Failed handshake closes owned handles and wipes secret bytes.

- [ ] Write feature-off and corrupt/bootstrap/wrong-peer/key/session/version/replayed-HELLO tests; owned native process and Python host must exchange authenticated request/reply through a real named pipe. Add timeout/partial framing/peer-exit and local-Stop-under-hung-peer witnesses.
- [ ] Run local/native tests; expected RED is absent actual startup/connection or unsupported production outbound traffic.
- [ ] Implement optional launch and replace App StartupUri-only setup with bounded bootstrap-aware startup and truthful standalone unavailable-host state. Retain standalone source chooser/Stop recovery, but do not create an implicit host permission or provider route.
- [ ] Run host/transport/native and protected feature-off checks; expected GREEN, zero live/private/provider actions.
- [ ] Preserve raw process evidence, secret-free diagnostics, rollback and owned commit.

## Task 4: Exact selection authorization and one-shot frame transfer

**Interfaces:** Native selected-source exchange uses the actual current `SelectedSourceReceipt`. Host returns authorization bound to session/source/revision/native capture epoch/consent/cancellation with remaining finite lifetime. `FrameTransfer.Publish(CapturedFrame frame, binding) -> typed opaque reference` owns a bounded Windows memory mapping; host consumes once, verifies dimensions/length/hash/current binding and deposits PNG bytes into existing EphemeralImageStore. No sender-selected arbitrary file/path/URL/mapping name is accepted.

- [ ] Write actual test-owned source selection→host grant→capture→memory→host digest witness. Assert zero pixels before grant, exact native/host source/epoch/digest, no JSON pixel bytes, refusal of missing/wrong/replayed authorization, foreign/reused/oversized memory, source replacement, lock/loss and Stop wipe/revocation.
- [ ] Run host/native tests; expected RED is actual capture still pending authorization or no host-owned frame transport.
- [ ] Wire current real selection and capture authorization, bounded mapping lifecycle and BGRA→PNG conversion. Preserve source instance and selection-attempt guards; read/write IO never holds the UI dispatcher or capture Stop lock. Close source-derived host sessions on replacement rather than mutating grants.
- [ ] Run full native executable and host/transport/gateway tests; expected GREEN including original unauthorized-capture and Stop cases.
- [ ] Preserve raw exact-digest evidence and owned commit.

## Task 5: Actual Ask button and validated visible answer

**Interfaces:** Add `SessionWindow.AskAsync()` used by real Ask Click, using NativeHostClient from Task3 and Task4 observation. Host chooses existing qualified provider/model/account/budget from current host configuration, not native text. Native answer consumes Task1/2 validated typed instruction, displays its explanation/citations/uncertainty and checks current request/session/source/revision/capture epoch/cancel generation immediately before render. No provider means Ask exposes the exact availability reason and makes no paid attempt.

- [ ] Write actual WPF Ask witness with a real owned Python host and controlled provider response; verify the exact source-bound returned answer is visibly displayed. Include double-click/idempotency, empty question, transport timeout, stale frame/answer, Stop/source change/pause/identity/grant revocation during pending dispatch, malformed answer and canceled Exit/close/summon continuity. Fixture route is host-injected only, never the production default.
- [ ] Run native/host tests; expected RED is missing Ask handler/no answer payload or stale release.
- [ ] Wire actual controls, progressive intent mapping, current source/Stop visibility, focus/accessibility names and explicit unavailability. Reuse existing reservation/accounting and tutoring policy; answering cannot create an assessment pass, action grant, overlay target or unrelated task cancellation.
- [ ] Run affected host/native/policy/learner/gateway/feature-off checks; expected GREEN. Real-model useful-answer/content/learning acceptance stays pending its approved campaigns.
- [ ] Preserve actual rendered/control proof and owned commit.

## Task 6: Independent review, final regression and original-scope checkpoint

- [ ] Obtain one fresh package review with Review focus above; grade effects, repair Important/Critical findings once with observed RED/GREEN and preserve Minors. No second reviewer pass or implementer delegation.
- [ ] Freeze the final candidate, run complete normal suite once, verify every source hash/restoration and terminal verdict, preserve every failed/skipped/unrun case and protected source proof.
- [ ] Save exact native executable/host/protocol versions, process-to-process frame/Ask evidence, rollback and remaining gates. SC-2D remains unaccepted until actual visible overlay, installed novice/accessibility and required human/provider/content evidence are present.
- [ ] Continue genuine source-origin/target/visible-overlay integration, onboarding outcomes and main Fleet discovery/return path; never treat this host/Ask package as the whole platform or final learner journey.

## Execution ruling and self-review

The owner already activated the original38-package plan and repeatedly instructed continuous building with Superpowers. This package executes SC-1A's existing actual host/request/capture instructions and SC-2D's existing Ask requirement using the preserved inline method; it creates no new external spend, permission scope or release. Additional diagram/research/conditional product requests remain in the full reconciliation. Do not ask again to execute already-authorized implementation.

Self-review: Tasks1/4 own exact host/native source admission; Task2 owns the typed wire and all signed fields; Task3 owns its real connection/lifetime; Task5 consumes those interfaces and releases actual visible content; Task6 preserves acceptance scope. All five Review focus cases have named witnesses. Source geometry/visible overlays, actual UIA target acquisition, installation/novice/accessibility, provider/content/human-learning and full buyer release are explicitly subsequent required work; this package does not claim their delivery. Host identity integration must use the sealed learning contract and live owner reader, never a fixture default or requester-supplied principal.
