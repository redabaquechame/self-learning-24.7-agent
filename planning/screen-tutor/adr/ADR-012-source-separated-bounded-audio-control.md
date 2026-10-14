# ADR-012: source-separated bounded audio control

**Status:** Accepted for implementation  
**Decision date:** 2026-09-15

## Context

Screen Tutor needs low-friction voice interaction without allowing a video,
system sound or the assistant's own playback to impersonate the learner. A
recognized phrase such as "yes, approve" is probabilistic text and cannot
replace the platform's governed confirmation path. Realtime audio also adds
device, latency, retry, queue and cost failure modes that must fail locally.

## Decision

1. Every transcript carries one immutable origin: `MICROPHONE`, `MEDIA` or
   `ASSISTANT`. Media is context only. Assistant playback is ignored as
   self-audio. No audio origin grants execution consent.
2. Microphone scope is explicit and capture is hold-to-talk. The idle state
   owns no stream. Releasing a current held capture may create a tutoring
   request, while any later action still follows the normal confirmation and
   Execution Authority contracts.
3. Audio requests carry a stable effect key, generation and source epochs, a
   bounded attempt count, and an accounting reservation identifier. Dispatch
   is invalid until a matching reservation exists. Retries reuse the same
   effect key and stop after two attempts.
4. Barge-in stops local playback, increments generation/playback epochs and
   cancels queued, reserved and in-flight obsolete work. Scope or device
   changes also invalidate prior audio. Late responses cannot revive playback.
5. Captions and text fallback remain available. Device loss releases
   push-to-talk and clears active audio state. Stop is local, terminal and
   idempotent.
6. `tutor_audio.py` and `TutorAudioSession` are control planes only. They open
   no microphone or speaker and call no network or model provider. A future
   adapter must use these decisions plus the existing provider gateway rather
   than owning a second dispatch or budget route.

## Failure criteria

- Reject missing, duplicated, unknown, wrongly typed, oversized or stale audio
  fields before they enter state.
- Reject media or assistant audio as a microphone submission and refuse any
  claim that voice alone authorized an external effect.
- Reject dispatch without reservation, duplicate identities, queues or history
  above bounds, retries above two, and responses from an obsolete epoch.
- Refuse provider, latency, device-matrix, echo-cancellation, accessibility or
  production readiness claims without the separate qualifying evidence.

## Consequences

- Source confusion and assistant self-trigger loops have closed, independently
  tested state transitions in Python and native code.
- Push-to-talk, interruption, stale suppression, retry, queue, device-loss and
  Stop behavior can be verified deterministically without recording anyone.
- The current implementation does not establish audio quality, live device
  behavior, provider latency/cost, speech accuracy or production integration.

## Reversal

Disable every audio entry point, cancel local playback and provider work,
release any adapter-owned devices, settle open reservations through the
existing gateway, and preserve append-only request/evidence records for audit.
