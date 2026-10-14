# Native capture original-deadline enforcement implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. One fresh whole-package review; no per-task delegation.

**Goal:** A capture delayed on the client gate must never start after original authorization expiry or receive a fresh duration by waiting.

**Architecture:** Preserve the shared Windows monotonic absolute expiry in CaptureSession. Validate both supplied authorization interval and current clock after acquiring the capture gate; delayed work cannot renew consent. NativeHostClient already passes remaining bridge lifetime; no host grant or transport schema changes.

**Tech Stack:** Existing .NET10.0.401/WPF/Windows App SDK2.4.0 and owned native form capture fixture. No dependencies, paid/private/device/cloud or release actions.

**Spec:** Original SC-1A/SC-2D selected-source, finite permission, local Stop instructions in `../planning/screen-tutor-v2-2026-09-14/execution/WORK_PACKAGES.md`; ADR002/013; existing maximum15-minute capture authorization and exact shared-clock timestamp contracts. Both products and every original qualification remain unaccepted.

## Global constraints

- Keep exact source/revision/epoch checks, maximum15-minute lifetime,3-frame/32MiB/64MiB bounds, feature-off behavior and local Stop semantics.
- Real tests use only a new owned constantly changing Windows form. Holding the test capture gate is a controlled scheduling delay, not a private source, provider or user-app action.
- Preserve all unrelated authored changes and immutable baseline locks. No commit/reset/push/deployment.
- Current onboarding/layout package native campaign passes; its final frozen normal is pending. Ruling: perform one combined final normal campaign after this independent capture repair and its review, instead of an intermediate normal followed immediately by another changed-source run. Each package retains its own source/log/review disposition; neither is accepted by a green combined campaign.

## Review focus

1. Gate delay outliving original expiry must refuse before allocating a capture pipeline or emitting pixels.
2. A shorter delay must preserve the original deadline, collect only while valid, then wipe and become unavailable under continuous changing pixels.
3. Future/mismatched clock inputs, wrong source and excessive lifetime remain refused; no duration normalization renews a permission.
4. Stop and source replacement cannot admit a late queued authorization; existing actual campaigns must remain green.
5. Tests must distinguish a valid capture from a vacuous zero-frame pass and keep current provider/private/human/device/release gates open.

## Task1: Real delayed authorization RED/GREEN

**Files:** Modify `companion/windows/ScreenTutor/CaptureSession.cs`; create `tests/native/ScreenTutor.ContractTests/CaptureDeadlineTests.cs`; add focused fixture/full-run dispatch in `tests/native/ScreenTutor.ContractTests/Program.cs`.

**Interfaces:** Existing `StartAuthorizedCapture(sourceId, sourceRevision, epoch, nowMonotonicMilliseconds, expiresAtMonotonicMilliseconds)` remains. Absolute clock is `Environment.TickCount64`. Tests receive the existing owned-window capture-item factory from Program; no new production source-selection hook.

- [ ] Write two actual owned capture witnesses: hold the real capture gate500ms with a250ms interval and assert expired start refuses/zero frames; hold700ms within a2000ms interval, require real pre-expiry frames, then assert no post-original-expiry receipt, unavailable state and empty buffers at original expiry+350ms.
- [ ] Build and run each focused fixture separately; retain observed behavioral RED and setup failures distinctly.
- [ ] After gate acquisition, validate current time against the original expiry, reject future supplied start clock, preserve existing interval/lifetime checks, and set the capture watchdog to the original absolute expiry rather than current time plus original duration.
- [ ] Rebuild and run both GREEN plus existing active-expiry/source/cancellation witnesses. Do not infer broader real-user/privacy qualification from owned forms.

## Task2: Review and shared regression

- [ ] Obtain one fresh read-only review of this bounded deadline package against the exact pre-package source pin; repair Critical/Important once with RED/GREEN, ledger all declined behaviors and Minor items.
- [ ] Run complete actual native/host campaign and affected Python boundaries. Preserve every failure and exact restoration.
- [ ] Freeze final combined candidate and run full normal once for both current packages; record source/artifact/log hashes and explicit skips.
- [ ] Save unaccepted progress/checkpoint and continue production owner/provider/Fleet discovery and genuine visible overlay/canvas; all original teaching/human/device/install/release/buyer gates stay open.
