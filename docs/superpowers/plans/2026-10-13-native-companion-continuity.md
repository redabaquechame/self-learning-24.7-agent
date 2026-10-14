# Native companion continuity implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the actual companion support Stop → explicit new selection and panel close → summon, preserving the original distinct-control semantics.

**Architecture:** Keep `CaptureSession.Stop()` terminal and create a fresh capture instance for a new explicit selection. Keep the window and registered summon shortcut alive when its panel is closed; a separate explicit Exit disposes them. Preserve session draft/goal and unrelated speech/task state, while old source callbacks and observations cannot enter the replacement session.

**Tech Stack:** Existing WPF, .NET SDK 10.0.401, Windows App SDK 2.4.0; existing compiled contract-test executable and Python compatibility suite.

**Spec:** `planning/screen-tutor/adr/ADR-013-companion-session-continuity.md`; original `../planning/screen-tutor-v2-2026-09-14/execution/WORK_PACKAGES.md`, SC-1A and SC-2D. This is one independent continuation package of the whole native journey, not SC-2D completion. Authenticated host capture/Ask/answer/overlay, actual accessibility/usability, provider/content and release gates remain required after it.

## Global constraints

- Preserve protected Fleet/Tutor work and exact source identity; the clean 179-script SC-1D candidate is preserved in `planning/screen-tutor-execution/evidence/SC-1D`.
- No private capture, paid provider, real-app input or deployment. Native witnesses use test-owned windows and deterministic fixture text only.
- Every new selection still requires an OS picker and a fresh exact host authorization before pixels; never revive a closed capture or reattach an old source automatically.
- Panel close changes panel visibility only. Speech stop, sharing stop, task cancel and Exit remain distinct; retained draft/goal does not grant source access.
- Do not promote compiled mechanisms into installed learner, human, real-provider or release acceptance.

## Review focus

1. A callback from an old/disposed capture must not update sharing, observation or status after replacement; Task 1 pins it.
2. Stop during an outstanding picker must not admit its late selection; Task 1 pins source-instance identity and completion generation.
3. Panel close must retain a usable shortcut/window, without resetting or resurrecting source authority; Task 2 pins actual WPF close/summon.
4. Exit/window teardown must dispose capture and shortcut exactly once, with no hung worker delaying local Stop; Task 2 pins idempotent exit and closed capture.
5. Failed/cancelled selection and unavailable source must leave an explicit, usable next selection path, never a fallback capture; Task 1 pins unavailable/cancel handling.

## Task 1: Actual Stop and explicit reselection

**Files:** `companion/windows/ScreenTutor/SessionWindow.xaml.cs`; `tests/native/ScreenTutor.ContractTests/Program.cs`.

**Interfaces:** Retain existing `CaptureSession` semantics. Add internal `CaptureSession PrepareCaptureSelection()` on `SessionWindow` for the real handler and compiled friend test; it stops/disposes an old closed source, resets source-bound UI/session state and starts the new explicit selection. Capture event handlers are bound to their owning instance and ignore noncurrent instances. `SelectSource_Click` uses its captured local instance and refuses stale completion.

- [ ] Add a compiled STA test that invokes the actual Stop button, asserts source selection remains enabled, and proves a fresh preparation returns `Selecting` while old capture stays `Closed`, with no selected source or pixels before authorization.
- [ ] Add stale source-event/completion and unavailable-selection witnesses using the owning instance guard; no real private OS picker is needed for negative completion records.
- [ ] Build/run the existing native project with the exact restored SDK and locked restore. Expected RED: current Stop disables the chooser / actual replacement preparation is absent, not a missing SDK or compiler error.
- [ ] Implement the shared real preparation and owning-instance callback guards. Re-enable selection after local Stop; keep Ask/Pause disabled until the genuine downstream authorization/answer integration exists.
- [ ] Rebuild/run. Expected GREEN: actual window controls permit a fresh selection while the old closed source cannot be resumed or leak callbacks; existing capture authorization and Stop witnesses still pass.

## Task 2: Actual panel close, summon and explicit exit

**Files:** `companion/windows/ScreenTutor/SessionWindow.xaml.cs`, `SessionWindow.xaml`; compiled native test in Task 1's file.

**Interfaces:** Add internal `void SummonPanel()` used by the real shortcut message and tests, and internal `void ExitCompanion()` used by an explicit accessible Exit button and tests. Ordinary `OnClosing` preserves draft and hides/cancels the close; only explicit Exit performs resource teardown and closes the window.

- [ ] Add a compiled STA actual-window test: close retains draft/goal and the same usable window; summon reopens/focuses Question; sharing/speech/task state is unchanged by panel close. A stopped source remains stopped across summon.
- [ ] Add explicit Exit/idempotent disposal test; old callbacks cannot reopen the panel or update state after Exit.
- [ ] Build/run to observe RED against current destructive `OnClosing` behavior.
- [ ] Implement panel hide/summon plus a distinct accessible Exit. Do not call the view-model close method and then dispose the capture/shortcut as if close meant Exit.
- [ ] Build/run to observe GREEN with all existing native checks retained.

## Task 3: Review, affected checks and exact evidence

- [ ] Run affected Python native-session, feature-off, environment-lock, package/frontend checks and `git diff --check`; preserve failures and source restoration.
- [ ] Obtain one fresh whole-package review, repair material findings with observed RED/GREEN in one bounded fix pass, and ledger all rulings.
- [ ] Freeze the final code candidate and run the complete normal suite once; preserve every skip and exact identity.
- [ ] Save compiled/native and full-suite evidence, source hashes, rollback and remaining authenticated/native/human/provider/content gates. Keep SC-2D unaccepted until its original positive/negative acceptance and evidence tiers are met.

## Execution ruling

The owner already activated the original full implementation plan and repeatedly instructed continued building with Superpowers. This document implements the accepted ADR's existing control semantics and retains the chosen inline method; it adds no product scope, external spend or release action. Continue within that authorization. Do not stage unrelated authored changes; any eventual commit must preserve the complete reviewed dependency candidate rather than publish an incomplete native-only branch.
