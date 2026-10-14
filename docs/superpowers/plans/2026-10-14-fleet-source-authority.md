# Fleet source approval and native launch implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, task by task. One fresh whole-package review, no per-task reviewer/implementer agents.

**Goal:** Connect Fleet's authenticated owner/project and existing exact-call approvals to native source authorization, preserving selected-but-unshared sources through approval and explicit retry, then expose truthful launch/discovery and return to Fleet.

**Architecture:** Add a host-only source approval authority over existing approvals/org and a runtime registry bound to authenticated actor/project. Native only supplies a closed selected-source receipt; it never chooses user, grant, account, model, ceiling or executable. Source scope is an existing owner-approved exact call, viewed through existing SessionGrantView, not a new standing grant kind. The companion must retain a selected receipt without capture while approval is pending and authorize only after explicit retry of the same current source.

**Spec:** Original SC-1A/SC-2D technical contracts and shared learning-service/owner trust boundaries; original Fleet interface discovery/approval/current owner and task lifecycle requirements. Both products, all38 packets and86/84 families remain scope. r58 image-dispatch frozen campaign must finish before source/test/doc/metadata edits.

## Global constraints / root rulings

- Preserve protected original Fleet core and inherited unaccepted execution/UI exceptions; no new blanket staging/commit/push/deploy.
- Test only owned Windows forms, isolated Fleet/org folders and loopback profiles. No private picker, real funded provider, mic/device or cloud activation.
- `approvals.request/decide` and existing `org.check` with declared run/approve permissions are the authorization machinery. Do not invent a capture standing-grant kind or let native/model content create a granted record.
- Authenticated actor comes from Fleet request authentication. Never accept user/tenant/project/permission/approval/route/executable from untrusted body text.
- Existing original backend Learn is Agent training/pursuit; native human learning must use shared learning.v1 and must not claim those pursuits are human submissions or independent outcomes.
- No provider defaults or spontaneous paid calls. Closed backend/current account/profile/budget scope is mandatory; launch remains unavailable with a clear reason if host executable/owner route is unqualified.
- Session source approval lifetime begins at original request, counts time spent pending, never renews on retries. Stop/source replacement/actor switch retires pending and granted source work.

## Review focus

- Pending source approval must produce zero pixels/exports and preserve explicit selected-not-sharing state; cancellation cannot become a late grant.
- Shared actor/token/project/account/provider-policy changes must retire or refuse exact stale authority, not reuse another member's session.
- Approval/grant/source epoch/handle/retention/budget scopes must be exact, and denial/pending status must stay truthful.
- Source/body/executable/endpoint injection must not bypass Fleet authentication/RBAC/CSRF or native bootstrap verification.
- Runtime launch/Stop/server teardown/return-to-task must be owned and bounded; no orphan companion or durable/background claim from a thread.

## Task1: existing-approval-derived source authority

Owned draft paths proposed: new tutor_authority.py and tests; tutor_host.py optional typed source authority installation; existing approvals/org unchanged unless a concrete verified defect requires its own ruling.

- [ ] Pin exact bases after r58 terminal/archive; install plan and meaningful missing-source-policy RED.
- [ ] Implement typed SourceApprovalAuthority(home, expert_root, current_context, *, clock_ms, lifetime_ms). Context is host-authenticated principal/tenant/project/actor plus exact source purpose, current provider/model profile, retention and budget-policy/ceiling references. No raw credentials in approval records.
- [ ] Validate selected receipt before creating `approvals.request` for an immutable exact current context+source+attempt. Read granted/denied/pending from existing records; only the existing owner decision can grant. Keep first requested expiry and bounded retired/pending custody.
- [ ] Provide current owner/source and SessionGrantView readers compatible with NativeTutorHost and ImageProviderRoute; bind host-generated learning session afterward without making native receipt authority. Reject actor/permission/profile/source changes on every read.
- [ ] Hook optional typed source authority into host selection before current source authorization; exact SOURCE_APPROVAL_PENDING/DENIED refusal without opening a learning capture session or reading any frame. Stop retires pending source even before a session exists. Preserve original injected-current-policy callers.
- [ ] Prove real isolated approvals/org permissions and exact-call pending/grant/deny, duplicate/replay/expiry, actor/project/source/handle/epoch/profile/retention/budget changes and Stop. No real private or paid evidence.

## Task2: pending native source and explicit retry

Owned paths: NativeHostClient.cs, SessionWindow.xaml/.cs, capture/session state only if necessary; native tests/owned host pipeline.

- [ ] Observe RED for pending approval causing source loss or implicit capture. Add typed pending response handling without changing closed bridge grammar: current reason_code is machine-readable, detail is user text.
- [ ] Retain same selected receipt/native item with zero frames; show Selected, not sharing and approval-pending/denied explanation, Stop and explicit Retry authorization. No automatic source switching or polling-to-capture permission.
- [ ] Retry only current receipt/epoch/current host authority. Stop/replace/Exit cancels retained approval attempt; late completion cannot restart capture or overwrite a newer attempt. Existing caption/onboarding/Ask source progress stays truthful.
- [ ] Actual owned selected window→pending existing approval→zero pixels→owner decision→explicit same-source retry→current capture→metered loopback Ask→visible answer→Stop/return path. Also denial, approval after Stop and account/source changes.

## Task3: Fleet runtime discovery and launch

Owned paths: new tutor_runtime.py, narrowly scoped ui.py routes and ui.html launch/status/return controls, auth/route tests and browser/native fixtures.

- [ ] Registry scopes to authenticated actor and existing expert project. Build one shared learning.v1 service; no independent success when human/course/exposure qualification is absent. Validated native executable is trusted host configuration, never a web path.
- [ ] Add declared same-origin/RBAC status/launch/stop routes; current actor proof remains checked while native is running, so token/role/project changes cannot preserve capture. Local device ownership/remote/shared actor constraints are explicit rather than guessed.
- [ ] Fleet button shows Available/Unavailable/Pending with precise owner/native/provider prerequisites; preserve original task context and provide return link. Never silently enable a real provider from stored credentials.
- [ ] Owned real browser/API/native positive plus viewer/CSRF/foreign actor/project/revoked token/unavailable executable/Stop/server teardown negatives. Do not claim installed or real novice acceptance.

## Task4: review/freeze/whole-program continuation

- [ ] Verify configured model-name admission; current image gateway and route use identifier rules that may exclude valid declared dotted/namespaced/colon model names. Reproduce with a synthetic declared model name, and fix the closed host configuration data boundary if confirmed; do not call it provider qualification.
- [ ] Register actual tests/modules/counts exactly; one fresh whole-package review/root repair pass and one final clean frozen campaign with source/native archives.
- [ ] Record partial current receipts and requirements comparison, including every decline-to-judge ruling. Continue genuine source placement/overlay, human upload/shared exposure/stateful teaching, all content/institution/audio/device/CU/Fleet/installer/release work. No stop after this package and no product/packet acceptance from mock/owned source evidence.
