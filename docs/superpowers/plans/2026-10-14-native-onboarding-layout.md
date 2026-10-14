# Real companion onboarding and reachable sharing controls implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox (`- [ ]`) syntax for tracking. One fresh whole-package review follows the implementation; no per-task delegation.

**Goal:** Stop demonstration clicks from claiming actions they did not perform, and keep source/Stop controls reachable at the supported minimum window size.

**Architecture:** Onboarding requests actions from the existing SessionWindow handlers; the window advances the checklist only after real local milestones. A fixed source/sharing strip remains visible while introduction, onboarding, question, answer and optional controls scroll in the remaining space. Existing capture/host authority, Ask release checks, panel continuity and local Stop stay authoritative.

**Tech Stack:** Existing WPF/.NET10.0.401/Windows App SDK2.4.0, existing actual owned-window/host fixture and native contract project. No new dependencies.

**Spec:** Original `../planning/screen-tutor-v2-2026-09-14/execution/WORK_PACKAGES.md` SC-2D instructions1–6 and `planning/screen-tutor/adr/ADR-013-companion-session-continuity.md`. Native installed novice/highlight/circle, useful real-provider, independent learning, accessibility/human/device/release remain mandatory and unqualified.

## Global constraints

- Finish the current frozen normal campaign before changing any candidate source; this draft is in the ignored package workspace solely to preserve source freeze. Copy to `docs/superpowers/plans/2026-10-14-native-onboarding-layout.md` before implementation.
- Preserve authored dirty/untracked work and the twelve protected baseline files, including declared unaccepted execution/UI exceptions. No wholesale staging, commit, push, deployment or source reset.
- No private source, real device/microphone, paid provider or real-app mutation in witnesses. Actual Windows forms/processes and injected fixture answers only.
- Minimum window remains380×440; text must remain scrollable and keyboard reachable. Source/Stop visible and synchronous, not hidden inside the expanding tutorial.
- A click is an action request, not completion evidence. No unsupported useful-answer, highlight/circle or learning-success claim. Visual guide completion remains blocked until actual visible overlay/circle integration is implemented.
- Closing the panel retains allowed draft/goal and unrelated work; Stop/Pause revoke applicable current observations and guide progress.

## Review focus

1. Clicking the checklist without an attached host/source/provider must not advance SELECT/ASK/SHOW or claim useful work; Task1 exercises actual button events.
2. Cancel/refused selection, late/invalid answer and changed source cannot leave stale checklist completion; Task1 extends existing actual negative fixtures.
3. Duplicate checklist requests cannot start a second picker/Ask or revive closed capture; Task1 delegates through guarded existing handlers.
4. Expanded onboarding, long selected-source/status text and18-point text at380×440 must not hide source/Stop; Task2 measures real arranged WPF bounds.
5. Keyboard focus/BringIntoView, panel close/summon and Stop continue to work after scrolling; Task2 verifies actual controls and existing native campaign.
6. Missing speech/task host integrations cannot display a false stopped/cancelled success or mutate a view-model flag as if a real Fleet task were cancelled; Task1 exercises actual buttons with absent and merely attached task IDs.

## Task1: Connect onboarding to actual guarded actions

**Files:** Modify `companion/windows/ScreenTutor/Onboarding.xaml[.cs]`, `SessionWindow.xaml.cs`, `tests/native/ScreenTutor.ContractTests/Program.cs`; extend `tests/test_tutor_connection.py` actual controlled journey assertions.

**Interfaces:** `Onboarding.ActionRequested` is an `EventHandler<string>` carrying existing SUMMON/SELECT/ASK/SHOW/STOP only. Existing `CompleteStep(string)` updates the presentation projection; checklist clicks never call it directly. Add `TryCompleteStep(string) -> bool` for idempotent in-order window notifications, and `InvalidateSourceProgress()` / `InvalidateAnswerProgress()` to reset only source-dependent progress. The window routes action requests through `SummonPanel`, guarded `SelectSourceAsync`, `Ask_Click` and `Stop_Click`; SHOW explains actual unavailability without completing a guide.

- [ ] Write native `ActualOnboardingActionTest`: real checklist SUMMON displays the panel; SELECT with no host cannot mark an authorized source; ASK without ready source cannot advance; SHOW button cannot manufacture visible guide/complete; Stop does not manufacture the prior stages. Existing actual host fixture checks SELECT after genuine authorization and ASK only after validated current answer, while no-provider/changed/invalid/timed-out responses do not advance.
- [ ] Build/run focused fixture and preserve observed RED caused by self-marked click progress, not setup/compiler errors.
- [ ] Implement action-request event and real milestone notifications. Source selection progress follows exact successful host authorization/current capture; Ask follows current validated answer presentation. Source replacement/loss/Stop resets source progress; answer invalidation resets answer progress. Duplicate actions obey existing picker/Ask guards.
- [ ] Update product-facing checklist copy to ordinary source/question actions, replacing synthetic implementation instructions and unsupported useful-answer/highlight/circle claims. Visual guidance remains truthfully unavailable until its real integration exists.
- [ ] Add actual unsupported task/speech button negatives and observe false cancellation/speech status RED. Keep unavailable actions accurately disabled/explained; do not call the view-model cancellation flag as a substitute for the missing real Fleet cancellation route. Preserve independent view-model contract tests and sharing/draft/task identity.
- [ ] Rebuild/run focused native and actual controlled valid/invalid/refused/canceled fixture checks; record exact proof scope and remaining visual journey.

## Task2: Make minimum-window content reachable

**Files:** Modify `companion/windows/ScreenTutor/SessionWindow.xaml`; native actual layout test in Task1's owned test file.

**Interfaces:** Root Grid rows Auto/*/Auto. Fixed source sharing strip contains indicator, bounded readable source title and wrapping Choose/Pause/Stop buttons. Central named `SessionContent` ScrollViewer contains header, instructions, onboarding, intents, composer, Ask, answer/evidence, status and optional speech/task actions. A compact persistent Exit footer closes resources explicitly. No handler/control names are removed.

- [ ] Write `ActualMinimumWindowLayoutTest`: shown real SessionWindow at380×440 with expanded onboarding and long status/source text; at default and18-point font, Stop and source strip have positive fully client-visible bounds; each composer/Ask/status/optional control can be brought into view and receives focus where focusable. Retain focus and draft across actual close/summon, preserve Stop behavior.
- [ ] Build/run to observe actual clipping/unreachable control RED in current XAML.
- [ ] Implement the fixed sharing strip and scrolling body; wrap action buttons and bound the visible source label while its full accessible name/tooltip remains available. Keep ordinary source and Stop labels.
- [ ] Rebuild/run focused layout and Task1 action fixture; all actual capture/Ask/interruption native checks must remain green.

## Task3: One review, regression and exact remaining gates

- [ ] Self-check against original SC-2D requirements and this review-focus list. Keep source geometry/visible overlays/practice/native human/real-provider qualification explicitly open.
- [ ] Obtain one fresh read-only whole-package review; repair Important/Critical findings once with RED/GREEN; ledger Minor/declined items. No per-task reviewer or second pass.
- [ ] Run affected Python contracts/host/feature-off/package/frontend and actual native checks, then one frozen full suite after final changes. Preserve all failed/setup/corrected fixtures and explicit skips.
- [ ] Record source/artifact/log hashes and updated unaccepted checkpoint. Continue production owner/provider/Fleet discovery and genuine visible overlay/canvas under the original whole-platform mandate.

## Execution ruling

The owner explicitly asked to continue both products under Superpowers. This package repairs existing SC-2D behavior rather than inventing a new product design. Inline execution continues without another check-in. Commits remain deferred pending authored-source ownership disposition; none of these local checks accepts SC-2D or either product.
