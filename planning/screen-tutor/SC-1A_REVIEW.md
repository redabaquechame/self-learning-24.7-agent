# SC-1A Windows capture and local bridge review

**Scope:** optional WPF companion, selected-source capture, bounded transient
frames, local bridge, summon/Stop controls, host session adapter, and native
contract witness.  
**Review dimensions:** security, correctness, performance, maintainability.  
**Current verdict:** approved for SC-1A local and test-owned Windows-source scope.

## Resolved findings

1. **Selection could have implied capture before host authorization.** The OS
   picker now produces only an opaque source receipt. Pixel collection starts
   only when the host presents the exact source ID, source revision, capture
   epoch, and a finite authorization no longer than fifteen minutes.
2. **A second authorization could restart an active capture.** An active native
   session now refuses a second start, so the same authorization cannot reset
   the frame pool or erase its history.
3. **Hostile authorization timestamps could overflow lifetime arithmetic.**
   Expiry ordering is validated before subtraction, and overlong grants fail
   with a distinct bounded-lifetime error.
4. **A presentation event handler could interrupt capture teardown.** Source
   loss now invalidates the native pipeline and clears frames before failure
   notification. Event handlers are isolated so one faulty subscriber cannot
   block cleanup or later subscribers.
5. **A hung structural provider had no explicit Stop witness.** Observation-only
   structural calls now run on a background MTA thread, accept a maximum
   ten-second deadline, allow one in-flight call, poison the worker after a
   timeout, and never join the provider during Stop. A native test holds the
   provider deliberately and verifies Stop returns in under one second.
6. **Frame ownership could outlive the selected source.** Every frame carries
   source ID, source revision and capture epoch. Pause, Stop, source close,
   watchdog loss, selection change and failed copy wipe all queued byte arrays.
7. **A local process could replay or confuse bridge messages.** The named pipe
   checks current-user peer ownership, HMAC, session, bridge epoch, strict
   sequence, monotonic deadline, maximum frame length and duplicate JSON keys
   before returning the body.
8. **Shortcut conflicts could silently take over another assistant's binding.**
   Registration now reports the conflict and exposes an explicit alternate
   binding. The original registration stays untouched.

## Security assessment

- The companion is optional and feature-off imports no native dependency,
  starts no process, opens no network connection and calls no model.
- Windows Graphics Capture receives one OS-selected surface. There is no
  desktop enumeration or foreground-following fallback.
- Picker selection alone yields no pixels. A foreign, stale, expired, overlong
  or replayed host authorization yields no frame access.
- Raw BGRA bytes remain in a bounded memory queue only. Eviction and lifecycle
  invalidation overwrite owned arrays before releasing them.
- Diagnostics expose dimensions, format, identifiers, monotonic time and
  digests; they contain no window pixels or structural labels.
- The structural worker accepts observation results only. It exposes no click,
  key, invoke, value-set or other application-input operation.

## Correctness assessment

- The native witness captures a real test-owned black/white Windows form and
  verifies 322 by 272 pixels, 350,336 bytes, more than 10,000 dark and 10,000
  light pixels, and a SHA-256 receipt over the exact copied bytes.
- Source closure transitions to `SourceUnavailable`, stops the native session,
  removes the source and clears the frame queue without selecting a fallback.
- The host service validates that every requested source has one matching
  observation and dispatches only the requested validated observations.
- Pause and reconnect advance or enforce epochs. Stop is terminal and
  idempotent in both the host adapter and native components.

## Performance assessment

- Frames are capped at three, 32 MiB each and 64 MiB total. The frame callback
  permits one copy at a time and drops extra arrivals while a copy is active.
- `CreateFreeThreaded` keeps frame arrival off the WPF dispatcher. Pixel data is
  deep-copied before the native frame is disposed.
- Local Stop does not await the model, bridge peer, frame callback or structural
  provider. The native hung-provider and hung-pipe witnesses both return within
  one second.

## Maintainability assessment

- .NET SDK 10.0.401, Windows App SDK 2.4.0 and NuGet transitive versions are
  locked. Native source and lock files ship; `bin/` and `obj/` do not.
- Capture, structural observation, UI, shortcut and bridge lifecycles have
  separate classes. The Python host entrypoint depends on injected gateway and
  render adapters.
- Protocol source vocabulary includes `SELECTED_SURFACE`; opaque IDs carry
  source authority rather than native handles or display names.

## Evidence boundary

SC-1A is accepted at `LOCAL_AND_NATIVE_SYNTHETIC_VERIFIED_REVIEWED`. The native
witness uses an interactive Windows session and a real test-owned source. It
does not qualify the user-driven private-source picker journey, OS permission
revocation UI, every minimize/device-loss path, a separate companion process
crash, installer/uninstaller, signed packaging, driver/device matrix, provider,
deployment, usability, accessibility, learning efficacy or release. Those
remain owned by later qualification packets and cannot inherit this verdict.
