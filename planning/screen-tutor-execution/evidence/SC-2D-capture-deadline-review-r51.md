# Independent capture deadline review and root disposition

One fresh read-only review by `/root/capture_deadline_package_review` checked all five candidate hashes and three pre-package copies. Verdict: **With fixes, bounded package only**. No Critical finding; one Important and one Minor. No second review was requested.

- Important: permission could expire during real D3D/frame pool/session initialization before native StartCapture. A trusted internal constructor seam, absent from the public default, delays that real initialized pipeline500ms against a250ms original grant. The observed RED reported native startup after expiry. The root repair checks the original absolute clock immediately before StartCapture, disposes the allocated pipeline and refuses on expiry. GREEN verifies refusal, zero frames and null session/frame pool/device/cancellation resources. This same guard covers initial startup and resumed capture; it cannot make operating-system scheduling atomic with clock validation.
- Minor: fixture readiness waited outside cleanup. Source startup/readiness now sit inside the cleanup scope; a shutdown flag handles late Shown, existing owned handles receive Close, and the source thread is background with a bounded join. This is a source repair; no separate injected readiness-timeout qualification is claimed.

Explicit rulings on declined review scope:

- Combined native/host and frozen normal regression remain required after this repair. Pre-repair passing logs remain historical. The first post-repair connection launch used an incorrect target-framework path and skipped actual connection; that log is setup evidence only. Its complete native campaign is recorded separately. A correctly selected actual host campaign must pass before final receipt.
- Real user selection/consent, private applications, providers, device/install and production readiness remain unqualified. Owned constantly changing forms prove only controlled capture mechanics.
- Both products end to end, onboarding acceptance and teaching/release/buyer gates remain open. No acceptance counts change.
- Quiet-source teardown timing remains the unchanged periodic watchdog behavior, not newly qualified by the continuously changing source.
- Subscriber event-delivery timing after an already queued receipt remains outside this package; tests check receipt timestamps. Do not equate them with an atomic subscriber-time authorization guarantee.

Original source/revision/epoch, finite interval, maximum15-minute lifetime and pixel bounds remain. Public imports/default construction add no fixture delay or external behavior. No provider/private/device/cloud, commit, release or deployment action occurred.
