# Independent onboarding/layout package review and root disposition

One fresh read-only review by `/root/onboarding_layout_package_review`, against the seven pinned pre-repair source hashes in `.superpowers/sdd/2026-10-14-native-onboarding-layout/review-source.json` and archived revision51 source. Reviewer inspected source and actual logs; no tests/builds, edits or second review. Verdict: **With fixes — bounded package only**. No Critical finding, one Important, two Minor. Full normal after new source was pending at review.

## Findings and one root repair pass

- **Important: host controls leave source progress completed.** `AttachHost` cleared answer/capture but did not invalidate onboarding source progress. Actual host revocation checks now require step1, SELECT enabled, ASK disabled. Initial actual RED exited before its native diagnostic was printed; retained as limited failure evidence. A test-owned regression mutation removing exactly the repair reproduces the precise native failure, now preserved in the terminal diagnostic; source bytes were restored exactly and rebuilt. The common callback now invalidates source progress on STOP/PAUSE/UNAVAILABLE/DISCONNECTED. Actual revocation before an answer and after a displayed answer passes. Full UI disconnection/device qualification remains open; common-handler coverage is not a separate installed-disconnection qualification.
- **Minor: disabled controls hide their explanations.** Task/speech and checklist SHOW now provide explicit accessible help and disabled-control tooltips; ordinary visible text also explains unavailability. Actual UIA help metadata is exercised, but no human assistive-technology acceptance is inferred.
- **Minor: layout evidence omitted populated answer/evidence and focus recovery.** Extended actual380×440/font12+18 fixture populates answer/evidence/status, intersects every ancestor scrolling viewport, tests enabled Ask focus, exercises in-process WPF next-focus traversal, and closes/summons after scrolling with visible keyboard focus/draft checks. This qualifies that controlled WPF mechanism, not physical keyboard/assistive-technology/browser/device/human acceptance.

## Explicit root rulings on every declined behavior

- Useful real-provider output: remains required; fixture presentation is not usefulness or provider qualification.
- Visible highlight/circle, safe practice, source origin and overlay/canvas: remain required; accurate unavailability does not complete these features.
- Speech/device operation and actual Fleet cancellation: remain required; disabled controls avoid false effects only.
- Novice completion, two-minute usability and first meaningful success: require human installed-journey evidence.
- Screen-reader announcements, contrast, reduced motion and full100–200% scaling: remain unqualified; UIA metadata and12/18-point local bounds are partial evidence only.
- Two-monitor/DPI/device matrix: remains required beyond the measured local client geometry.
- Private/real OS picker usability: remains unqualified; owned injected source tests exercise downstream authorization without private capture.
- Keyboard focus after scrolling: new actual WPF witness closes the specific local gap; broader human/physical keyboard/assistive-technology acceptance stays open.
- Dashboard/CLI discovery, return-to-task, production identity/grant/provider/Fleet integration: remain mandatory next integration work.
- Installed journey, packaging/install, deployment/release and whole platform: remain unaccepted.
- Current full normal: must pass after this one root fix pass; earlier revision51 result is historical and preserved.
- Grant/security/provider semantics outside changed call sites: prior machinery remains required and preserved, with no claim of a fresh security or provider re-audit from this UI review.

No family, packet or product is accepted by this review. Canonical ownership/selective commit and the two protected baseline exception dispositions remain open. Continue the original both-product implementation rather than stop at these repairs.
