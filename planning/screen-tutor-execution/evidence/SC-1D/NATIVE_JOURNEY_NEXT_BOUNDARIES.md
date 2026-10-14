# Source-checked native journey resume findings

These are preparation notes, not product delivery or a replacement plan. The original full Fleet + Tutor objective and packet acceptance criteria remain intact.

- SC-1D requires LOCAL, PROVIDER and CONTENT_REVIEW. Its original instruction explicitly requires useful pack-free text plus a reversible sample with verification if supported; unsupported actions stay explicit. Current adapters deliver mechanically checked assisted copies, not real-app actions or human learning.
- SC-2D requires an installed synthetic novice journey summon → select → useful answer → highlight → Stop, actual user friction evidence and keyboard/screen-reader/draft/close/cancel continuity. Existing synthetic checklist is insufficient.
- SessionWindow.xaml Ask is disabled and has no Click handler. SessionWindow.xaml.cs owns an isolated CaptureSession but does not create/connect OwnerBridge or call StartAuthorizedCapture. Selection displays not sharing yet; it cannot produce the authenticated answer journey as written.
- OwnerBridge.cs is an authenticated, current-user-only framed server/reader, not a bidirectional host-to-Fleet request dispatcher. Any new transport must preserve exact session/epoch/sequence/deadline/MAC and local Stop boundaries.
- SessionWindow Stop_Click calls CaptureSession.Stop, which closes capture, and disables SelectButton. Closing disposes capture/shortcut and closes the window; view-model-only reopen tests do not establish actual summon/reopen continuity.
- FrameAvailable currently updates status and binds only frame digest in SessionViewModel; it does not dispatch an observed request, provider answer or production overlay.
- Next work after full-r2 terminal/hash restoration: finalize exact SC-1D evidence and its open provider/content gates, then define an additive authenticated native orchestration plan from the original SC-1A/SC-2D specs. Wire actual host identity/authorization/selection/capture/request/instruction, cancellation and reopen, with real compiled synthetic host and stale/revoked/hung negatives before claiming visible delivery.
- Do not select a paid provider, capture private applications, invent pack qualification, enable arbitrary client grants, or call a disabled mechanism a completed user flow. Continue eligible local work while external qualification is unavailable.
