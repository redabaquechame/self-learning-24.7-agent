# Native image-dispatch package review and root repair pass

One fresh read-only reviewer native_image_dispatch_review returned With fixes:0Critical,3Important,0Minor. Eight exact base,10 candidate and21 log pins matched before/after; HEAD160fa4bcb09f63680189a305664bb7cd37c8158a unchanged. Reviewer ran no builds/tests/writes/subagents. Original review pins stay historical. No second review.

## Important dispositions

1. Resolved credential identity: locators alone were pinned, allowing changed environment, agent.env or key-file accounts. All three supported synthetic-source mutations had observed REDs. Native dispatch now privately fingerprints the effective credential, verifies current identity on admission/retry/release, and uses a private per-dispatch Agent/configuration snapshot carrying exactly the approved credential. Before-dispatch and retry replacements refuse, and any recorded first HTTP uses only the approved synthetic account. Credential values remain private in process and are neither logged nor disk-pinned.
2. Queued native writer: pre-send checks ran before the send gate. Occupied-writer tests with budget and source changes actually emitted signed ANSWER REDs. Host now passes current connection/source-generation/provider authority into NativeConnection.send, checked after acquiring the gate immediately before serialization/write. A failure emits no answer, then produces an exact correlated QUESTION_REFUSED under the original deadline; the bridge remains healthy. Stronger assertions verify False outcome and one signed refusal; not an empty-write or exception-only pass. Connection pre-repair source is preserved separately under root-repair-base-source.
3. Effective output cap: mutable Agent.max_output_tokens was outside the account/configuration pin and reread after reservation/retry. Both after-reservation and retry cases had observed REDs. Pin now includes it; the private dispatch snapshot supplies a fixed bounded effective cap to both estimation and every actual HTTP payload. Changes refuse before a larger or extra request. A configured default cap is explicit in the snapshot, so cap0 cannot omit an output bound from the paid request.

Ruling: preserve original protected Fleet core. Snapshot an existing Agent without initialization and invoke its unchanged qualified gateway/model loop; no new grant issuer or third protected-file exception. All12 files still match the existing unaccepted candidate lock, with its two inherited exceptions retained; this does not approve those exceptions against the original immutable baseline. Ordinary callers remain unchanged. No hostile mutation of the trusted Python process or zero-time policy-to-OS-write guarantee is claimed.

## Every declined-to-judge item and root ruling

- Real provider answer accuracy/usefulness/calibrated uncertainty: remains external provider/human qualification; loopback mechanisms cannot establish it.
- Real pricing/account eligibility/operational budget: remains separately approved real-account/provider qualification; no paid route exercised.
- Provider-side deletion/retention: remains provider evidence gate; local retention admission does not prove remote deletion.
- Production Fleet owner approval/grant issuance: remains unfinished; this consumes existing authority and the current native witness uses explicit synthetic host grants.
- Production launcher/discovery/return to task: next original work; not fulfilled by installing a callable backend.
- Private-source picker/arbitrary desktop acquisition: unqualified; owned form only.
- Microphone/voice/devices/speech accessibility: original image-independent packets remain open.
- Teach/Assess/Collaborate/annotations/actions/stateful practice: explanation route only; original richer product work remains open.
- Shared assessment exposure/independent learning eligibility: no outcome claimed; cross-surface production exposure publication still required before independent credit.
- Human content review/novice usability: open; mechanical diagrams/answers do not provide content or human acceptance.
- Installed distribution/deployment/release: open; no installed or deployed platform evidence.
- Running actual log/final normal185/source-native archives at review boundary: pre-root actual was terminal PASS after reviewer boundary, post-root actual now passes for current production bytes; two stronger queued-test assertions are separately focused and included in the upcoming frozen full suite. Exact full normal/archive gate remains pending here, no acceptance inferred.
- Unrelated dirty branch and historical canvas r56 acceptance: excluded; previous clean185 remains historical after these changes, and no packet/product acceptance was granted.

## Additional retained repairs and evidence

Host install and PNG wrong-digest REDs/GREEN; exact one-shot digest consumption and wipe. Twelve scope/grant/retention/budget/destination negatives, budget change during HTTP, actual owned PNG/native QUESTION/current grant-budget/loopback HTTP/metered visible answer with textual uncertainty, and Stop during exactly one HTTP request with one settled reservation pass. Existing native atomic metadata publication was preserved. Actual Windows exclusive handle reproduces PermissionError; bounded only-PermissionError receipt reader allows transient release and leaves permanent/missing/malformed failures visible. Setup failures remain separate: fixture teardown API/logger cleanup, nonexistent observation generation field, empty requested_response nonempty-contract mismatch, stable320x240 fixture dimension and one root patch anchoring correction.

Current native full uses unchanged compiled native bytes and passes. Post-root complete actual production campaign passes; focused stronger queued assertions pass. Clean frozen final185 suite and archives follow. Both products and packets remain unaccepted.
