# Current source approval projection implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, task by task. One fresh whole-package reviewer at the end, no per-task delegation. Keep the original both-product objective active after this package.

**Goal:** Show actionable sharing approvals only for the current native source attempt and refuse stale decisions after Stop, replacement, expiry, profile/token/role change or server restart.

**Architecture:** Add a read-only current-attempt view to the existing SourceApprovalAuthority and a registry projection that checks its original authenticated runtime proof. Fleet decorates existing approval records with that projection; it does not invent a granted record, change standing-grant kinds or forge a cancelled owner decision. Existing immutable approval history remains, with explicit retired/current state. Current pending approvals can be granted/denied; a current granted source can still be explicitly withdrawn.

**Tech Stack:** Existing Python stdlib Fleet/auth/org/approvals/shared learning.v1, browser UI and existing owned Windows fixtures.

**Spec:** Original SC-1A/SC-2D source/identity/consent/interruptible controls and Fleet exact-call approval/discovery/current-owner requirements. Immutable original plan at `C:/Users/redab/OneDrive/Bureau/self learning 24.7 agent/planning/screen-tutor-v2-2026-09-14/START_HERE.md`; technical contracts at `specs/TECHNICAL_CONTRACTS.md` beneath that plan. Current r60 source and105-file native archives are preserved and unaccepted.

## Global constraints

- Both products, all38 packets and retained86/84 requirement families remain scope; no handover acceptance from owned/mocked/native/loopback evidence.
- Preserve immutable baseline history; ui.py/ui.html remain explicitly unaccepted protected deltas. No broad stage/reset/commit/push/deploy. Scope to current package paths only.
- Existing `org.check` run/approve permissions and authenticated bearer/local-owner identity apply. Native/model/web bodies cannot choose actor/tenant/project/grant/account/executable/budget.
- No paid/private-source/microphone/device/cloud/installer activation. Isolated org/expert folders, loopback profiles and owned Windows forms only.
- No authority lock held while invoking a host/runtime callback; no runtime registry lock held while calling host/authority methods. Use generation snapshots and final checks to refuse races.
- Never extend the original approval lifetime on inspection, decision or retry. Expired/retired requests cannot revive pixels or provider work.
- Retain existing owner decision history; projection is read-only. Do not label a request denied merely because the host retired it.
- Current-source denial/withdrawal must keep existing Stop/revocation/late-answer behavior; ordinary MCP/agent approval decisions keep their existing semantics.

## Review focus

- Source replacement/Stop/expiry/restart cannot leave an actionable stale approval or allow a stale decision.
- Original token/role/profile/account/project/executable proof stays current during projection and decision, including an approver different from the local device member.
- Pending inspection opens no session/frame/provider call and grants nothing. Owner decision and original finite lease remain exact.
- Lock ordering and cancellation remain bounded; history cannot become native authority; late records cannot replace a newer current source.
- Mixed ordinary/source approvals, access-filtered source metadata, current granted-source withdrawal and browser error/retry states remain truthful.

## Task1: typed current-attempt projection

Owned files: tutor_authority.py, tutor_runtime.py, tests/test_tutor_authority.py, tests/test_tutor_runtime.py.

- [ ] Pin exact r60 bases, HEAD and source hashes before edits; retain successful frozen187 receipt.
- [ ] Write a RED showing that a retained pending record has no current-attempt projection after Stop or source replacement, and that the registry cannot distinguish current/retired source approvals.
- [ ] Add authority read-only `current_approval()` returning exact id/status/scope/first start/expiry only when context, generation, selected receipt, protected record key/args and finite lease remain current. Return no authority for denied/expired/retired/missing/tampered records. Host callbacks stay outside authority locks.
- [ ] Add runtime `approval_state(slug, approval_id)` projecting `CURRENT_PENDING`, `CURRENT_APPROVED`, or `RETIRED_OR_UNAVAILABLE`; validate the original runtime's current proof/profile/actor and selected authority. Snapshot registry entries before callbacks, then check entry identity again. No capture/session/provider side effects.
- [ ] Test pending/granted/withdrawal, wrong id/project/instance, Stop/replace/restart/expiry/tampered fields and authentication/profile/settings changes. Meaningful concurrent cancellation witness; no lock inversion.

## Task2: existing Fleet approval card/decision integration

Owned files: ui.py, ui.html, focused runtime/HTTP tests; docs/SCREEN_TUTOR_FLEET_HOST.md.

- [ ] Observe RED: a stopped source's retained pending approval can still be granted through the existing source decision route.
- [ ] Before source-specific decisions, load the protected existing record, ask the current registry projection, and refuse stale/unavailable scope without mutating the decision. Current pending grant/deny and current approved explicit withdrawal remain allowed under `approve` permission. No pursuit or capture starts from a decision.
- [ ] Existing approval read endpoint labels current/retired source records. Filter source metadata to its original actor or an existing approver; leave ordinary approval reads/decisions unchanged. UI replaces stale action buttons with a plain explanation; exact scope remains inspectable to authorized users.
- [ ] Source decision errors provide a refresh path, retain actor/expert context and do not claim capture started. Current denied-source and Stop paths remain exact.
- [ ] Actual isolated HTTP/browser current grant, withdrawal and retired-card refusal; owned native state/pending zero capture and current role/profile/Stop negatives. No real account/private picker acceptance.

## Task3: review, freeze, continue whole program

- [ ] Candidate baseline successor for current protected UI bytes, without rewriting prior locks; preserve pending source-ownership/acceptance gates.
- [ ] One fresh read-only whole-package review using Superpowers code-reviewer template and exact bases/candidate/log hashes. Root regrades and fixes Important/Critical findings once with watched RED/GREEN; preserve every Declined to judge ruling and defer Minors.
- [ ] Appropriate current native checks and one clean frozen187 registered campaign/source/native archive verification after final repairs. No repeat of unchanged green campaigns unless source/failure/coverage changes justify it.
- [ ] Update partial evidence/state/report without accepting a packet. Continue native human assignment/actual upload/shared exposure, real reviewed content/overlay, all remaining Fleet/interface/provider/computer/institution/device/installer/release and buyer gates. Do not end the turn after this package.
