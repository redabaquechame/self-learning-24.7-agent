# One independent whole-package review and root repair disposition

Review seat: `/root/native_host_package_review`, fresh context, read-only. Reviewed revision50 host/native Ask package and Fleet UI candidate against original host plan and retained qualifications. Source hashes matched the revision50 receipt. No reviewer tests or source writes. This document preserves the coordinator's summary of the returned review, not a new review or verbatim transcript.

Verdict returned: **Ready to merge? With fixes.** No confirmed Critical finding. This verdict covers this bounded package, not the entire dirty branch or product readiness.

## Important findings

1. **Completed frame leases keep occupying transfer capacity.** Native frame consumption wipes mapping bytes but the publisher retains leases until the original capture grant expires. Three small questions, or earlier large ones, can exhaust capacity. Root reproduced five actual WPF questions: only three provider dispatches before failure. Repair retires the exact transfer in `SendFrameAsync` finally, wipes before restoring capacity, and joins retirement during disposal. Actual five-question GREEN; timeout/retry exercises failed-frame cleanup; three sequential maximum32MiB transfers check every held-view byte is zero and capacity is restored. RED and GREEN logs remain in the package workspace.
2. **A late reply from a timed-out request can reach a later caller.** Authenticated correlation to any pending request is insufficient for a FIFO inbox. Root reproduced a timed-out real frame followed by a different real frame: the next question used the old observation. Repair registers per-message waiters before wire publication and delivers only the exact `reply_to`; canceled/unmatched replies are disposed without blocking controls. Actual timeout followed by distinct pixels and retry now selects the exact new observation and shows the controlled answer. RED and GREEN retained.
3. **Stale authenticated messages shut down healthy receive pumps.** The codec consumes an authenticated stale sequence but continuous native and host loops treated the resulting exception as fatal. Root reproduced both continuous-pump failures. Repair uses a dedicated native stale exception only for permitted established authenticated traffic and catches only that outcome in continuous pumps. Actual expired-envelope then current-envelope/ack tests pass both sides. Invalid authentication, shape, sequence, framing and non-established expired traffic remain fatal. Initial missing-runtime setup failure and fixture EOF/teardown race remain separately retained.

## Minor finding

**Search-palette dialog closes to a hidden invoker.** Root reproduced this in actual Chrome against an isolated owned Fleet. Palette closure now restores the original visible action before opening the dialog; dialog/palette close verifies usable focus and falls back to a visible navigation action. Browser RED/GREEN retained. New explicit unaccepted baseline successor pins this UI delta; original locks remain immutable.

## Root rulings on review boundaries

- Source ownership, selective commits and the two protected baseline exceptions remain open; no wholesale staging, commit, push or deployment is implied by the review.
- Real owner identity/current project/grants, main Fleet launcher/discovery, real provider/reservations/accounting/useful output remain required.
- Source origin, native UIA integration, visible overlay/canvas, broad private/app source diversity remain required. Test-owned windows and text answers do not meet those gates.
- Teaching/correction/assessment/independent learning, durable retention/transfer, task collaboration, qualified source rights/content, institution and employer integrations remain required.
- Installed novice, accessibility, locales, devices, minimum-window layout, onboarding/scaling, signing/update/migration/rollback/uninstall, soak/support and human validation remain required.
- Whole current normal and actual/native checks must pass after these repairs. Earlier green campaigns are historical and cannot certify changed source.
- Buyer scope, production deployment and handover acceptance remain required. All 38 original packet dispositions remain; no new acceptance or release claim follows from these repairs.

Ruling: perform the one authorized Critical/Important repair pass with observed RED/GREEN and current full checks, also repair the concrete Minor focus bug, and keep every declined qualification open. No second independent review pass is claimed or requested for this package.
