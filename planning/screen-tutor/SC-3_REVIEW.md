# SC-3 offline audio-control review

**Scope:** source-tagged transcripts, explicit audio scopes, hold-to-talk
capture state, execution-consent separation, reservation-gated request intents,
bounded queues/retries, epoch-based interruption, captions/text fallback,
device loss and local Stop.  
**Review dimensions:** security, correctness, performance, maintainability.  
**Current verdict:** locally verified and reviewed with deterministic native
state evidence; provider, live-device, content and human qualification remain
open.

## Resolved findings

1. **A video could say “approve” and impersonate the learner.** Media records
   are context only, assistant playback is self-audio, and all transcript
   classifications return `execution_authorized: false`.
2. **The assistant could hear and trigger itself.** `ASSISTANT` events are
   discarded as `IGNORED_SELF_AUDIO`; the selective mutation that removes
   this branch is caught by `test_tutor_audio.py`.
3. **An idle feature could maintain a hidden cloud stream.** Sessions start
   with push-to-talk released and zero requests. The new control classes own no
   device, network or provider object.
4. **A retry could duplicate an effect or exceed budget.** One request ID maps
   to one stable effect key. Dispatch requires an accounting reservation and
   attempts stop at two.
5. **A stalled network could grow work without limit.** Active requests are
   capped at four, request history at 32, transcript/response sizes are bounded,
   and exhaustion activates the existing text route.
6. **An interrupted response could speak later.** Barge-in increments epochs,
   stops playback and cancels obsolete work. Response acceptance rechecks the
   current generation and source epochs.
7. **A device or scope change could retain stale authority.** Scope changes
   increment source identity; disconnection releases capture and cancels work.
8. **Malformed JSON could change an event's source.** The native parser rejects
   duplicate, unknown and missing properties and validates types and bounds.
9. **Stop could wait for a provider.** Stop changes local state immediately and
   idempotently; it does not call a device or remote service.

## Evidence

- T046 proves media/assistant approval language remains non-authoritative, and
  a microphone transcript also cannot grant execution consent.
- Offline T048 proves barge-in cancels playback/work and rejects a late response.
- Offline T049 proves disconnection disables capture with text fallback.
- Offline T050 proves idle push-to-talk creates no outbound request.
- T051 proves reservation gating, two-attempt exhaustion, bounded queues and a
  stable effect identity under repeated network failure.
- The native contract test repeats source separation, self-audio suppression,
  push-to-talk, reservation, retry, playback, interruption, device-loss and
  Stop transitions without opening an audio device.

## Evidence boundary

SC-3 is not accepted as a complete packet. SC-1B has no authorized realtime
provider qualification, and SC-2B lacks its content/human qualification. No
live microphone, headset change, system/video capture, echo, speech-recognition
accuracy, warm/cold latency, provider cost, accessibility, supported-device
matrix, deployment or release test has run. The new code is an offline control
plane and native state witness, not a production audio adapter.
