# Native qualified image dispatch implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task inline. One fresh whole-package review, no implementer/reviewer per task.

**Goal:** Connect a current native Ask to Fleet's existing metered image gateway under exact current source, grant, destination and budget authority.

**Architecture:** Add a small typed dispatch facade in tutor_dispatch.py. The host installs it over its private one-shot image store and current observation/source readers; tutor_gateway.py continues to own qualified HTTP dispatch and reservation/accounting. Reuse existing TutorInstruction and SessionGrantView schemas; all real destination/budget/grant authority is supplied by the existing trusted host.

**Tech stack:** Python3.12 standard library; existing Fleet Agent/modelgateway, signed Python/.NET bridge, .NET10 companion; existing owned Windows Forms and loopback FakeProvider fixtures.

**Spec:** C:/Users/redab/OneDrive/Bureau/self learning 24.7 agent/planning/screen-tutor-v2-2026-09-14/specs/TECHNICAL_CONTRACTS.md; execution/WORK_PACKAGES.md SC-1B and SC-2D.

## Global constraints

No default enabling, new grant kind/issuer, credentials, arbitrary URL/file/image resolver, native-selected model/provider, paid/private source, mic/device, push/deploy or acceptance promotion. Preserve both-product original38 packets and86/84 requirement families. Existing immutable baseline exceptions stay unaccepted. Store image leases already use the gateway clock; bridge deadlines use Windows monotonic and must translate remaining time conservatively.

## Review focus

- Provider configuration/destination or budget ceiling changes after validation but before the next dispatch/retry must suppress output and unauthorized requests.
- Shared account/project/consent/retention/grant mismatches must refuse before exporting pixels; a native message cannot choose its own authority.
- Stop/source replacement while provider IO is pending must suppress the old result and avoid a second charge or renewed lease.
- Gateway textual uncertainty must survive into the visible explanation without inventing confidence, independent evidence or learning credit.
- A valid current image-only explanation must actually pass current TutorInstruction validation and reach the owned companion through the real HTTP/socket/pipe chain.


Both products remain incomplete. This package closes the missing NativeTutorHost-to-existing-qualified-image-gateway adapter. It does not replace the current-owner/provider-destination/budget authority with a native request, invent a grant kind, enable a provider by default or exercise a paid provider.

Spec: original SC-1B/SC-2D and SessionGrantView/TutorRequest/TutorInstruction contracts. Existing tutor_gateway.ask_image already owns actual HTTP dispatch, one-shot PNG custody, exact model capability, reservation-before-call, retry/cancellation and metering. Native host currently receives only arbitrary host-supplied instruction dispatch and has no installed gateway route. Preserve that injection for owned/offline tests and old callers.

Interfaces proposed for root ruling and pinned plan: typed host-installed ImageProviderRoute with an existing Agent, exact configured provider/model, trusted current SessionGrantView reader and budget-policy ceiling reader. Bind these readers to the existing host identity/project/session/source/consent/generation and current retention and budget refs. No native-supplied provider/model/path/key/destination. NativeTutorHost.install_image_provider(route) installs the dispatch closure over its private EphemeralImageStore and current source/observation. Only EXPLAIN/GUIDE and source-only images are supported. Missing/changed grant, provider destination, scope, policy, account/model/capability or budget refuses before bytes leave. Preserve grant-createdFalse and learning-successFalse.

Owned paths after the canvas frozen campaign ends: new tutor_dispatch.py; tutor_gateway.py digest-bound store admission; tutor_host.py; tests/test_tutor_gateway.py, tests/test_tutor_host.py, tests/test_tutor_connection.py; README.md/REFERENCE.md module counts150 if the dedicated facade is installed and exact owned native fixture metadata publication repair if confirmed. Do not alter immutable originals, UI/source approval semantics, default settings or real accounts. Existing modules/tests retain185 registration; documentation changes only if APIs require them.

Tasks: pin exact source and plan; observe missing install route RED; exercise one current PNG through real loopback HTTP/usage/reservation and native visible answer; test scope/destination/model/budget/retention/grant/Stop/source drift and original plain dispatch; adapt validated image result into an instruction with source uncertainty text and no fabricated numeric confidence/learning claim; translate remaining Windows bridge deadline conservatively into gateway monotonic deadline; bound answer to existing instruction limits; preserve failed setup/readback receipts; one fresh whole-package review/root repair; one clean frozen full campaign if source changes justify it; update partial receipts and continue real owner/Fleet launcher/discovery and all original packets.

Qualification remains local/owned/loopback. Real provider quality, usefulness/economics and approved production owner/key/budget remain separate open gates. Broader teacher actions/scenes/assessment/stateful practice are not claimed by an explanation adapter.

## Task1: typed source/grant/destination/budget adapter

- [ ] Install this draft as docs/superpowers/plans/2026-10-14-native-qualified-image-dispatch.md only after current frozen campaign finishes. Pin HEAD and exact base files with recoverable copies. Record that the current actual full r1 failed with transient read-sharing race and r2 passed unchanged; treat it as owned fixture publication/readiness work, not provider failure.
- [ ] Add focused tests under existing test_tutor_gateway/test_tutor_host. Missing tutor_dispatch/install_image_provider is the observed RED; assert real loopback HTTP, one inline image, no tools, exact current source, metered reservation and source uncertainty explanation, no invented credit.
- [ ] Implement ImageProviderRoute(agent, *, provider, model, current_grant_view, current_budget_view). Freeze construction policy and read live authorities for every admission. Budget view is a trusted current closed view with budget_policy_id, budget_reservation_id and ceiling_usd; those refs must match the request/current grant. Grant validator uses exact existing schema, including session, actor/tenant/project, consent/generation, source/capabilities/provider_destinations, expiry and retention. Destination match alone never implies useful provider qualification.
- [ ] ImageProviderRoute.dispatch(request, observations, *, store, current_owner, current_binding) admits exactly one current PNG observation for EXPLAIN/GUIDE and SOURCE_ONLY; binds owner/session/request/source/retention/consent/generation, checks current observation digest against stored bytes before gateway dispatch, computes the minimum request/observation/grant remaining lifetime and conservatively translates it to gateway monotonic time.
- [ ] Recheck current grant and current budget view from cancellation/current-binding callbacks throughout gateway dispatch. Provider/model fixed by host-installed route; requests cannot provide an override. Disallow install over existing active/in-flight provider/session without explicit stopped replacement semantics.
- [ ] Convert strict image result into closed TutorInstruction: answer plus original textual uncertainty within32768characters, no fabricated numeric confidence, no annotations/action, no quiz, EXPLANATION_AVAILABLE progress only. Source snapshot remains current evidence; no human learning claim. Malformed or oversized results refuse.
- [ ] Run focused source/destination/budget/model/retention/identity/Stop/stale/malformed/metering negatives and ordinary plain-dispatch compatibility. Keep RED/GREEN logs.

## Task2: real owned native + gateway witness and fixture publication reliability

- [ ] Install route into the existing current owned host fixture with loopback FakeProvider; use real admitted source pixels, gateway HTTP and the real native QUESTION/ANSWER/render path. Do not mock gateway itself as end-to-end proof.
- [ ] Observe controlled pending Stop/refused destination/refused budget/source changes; no unauthorized request or late visible answer, exact once reservation. Source/owner fixture identity remains explicit synthetic authority.
- [ ] For metadata race only, reproduce deterministic file handle held during metadata read or publish before complete. Repair owned fixture publication/readiness with preserve the existing native atomic publication and use bounded retry of exact owned-file sharing errors; do not hide other IO/malformed/provider failures. Keep original r1 failed/r2 passed logs.
- [ ] Run current full native and full actual owned connection campaign sequentially; failures preserved and relevant repairs only. Broader private/devices/production remains open.

## Task3: review, freeze and keep building

- [ ] Update real module counts and API reference; registrations remain185 unless a dedicated acceptance module is added, then update both classifications exactly.
- [ ] One fresh read-only package review of pinned base/candidate and Review Focus; root repair Important/Critical once; retain all declined-to-judge rulings. No second review.
- [ ] Freeze all final source/native bytes, one full normal campaign; require one terminal and unchanged source. Archive every source/native file and log hash, preserving skipped/failed evidence.
- [ ] Update partial SC-1B/SC-2D state, checkpoint and requirements report. Continue main Fleet owner approval/session/launcher/discovery, genuine source placement/desktop overlay and every original content/human/institution/provider/release requirement. Do not end work after this package or call either product ready.
