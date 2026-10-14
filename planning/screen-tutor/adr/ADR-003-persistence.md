# ADR-003: Durable tutor state and ephemeral screen data

**Status:** Accepted for implementation  
**Decision date:** 2026-09-14

## Context

Tutoring needs resumable goals, provenance, learner corrections, and effect
reconciliation. Screen pixels can contain credentials, private messages, health
data, or customer material and must not become accidental memory.

## Decision

The Python service owns durable, versioned, append-first records through the
existing file and evidence authorities. Store content-addressed source metadata,
consent scope, normalized anchors, decisions, citations, learner events, and
effect receipts. Use atomic replacement for projections and append records for
events. Every record carries schema version, task ID, capture-scope ID, origin,
timestamp, retention class, and deletion lineage.

The native shell holds selected pixels, OCR intermediates, masks, audio frames,
and native handles in bounded memory only. Raw capture persistence defaults to
off. A later explicit retained-capture grant must name purpose, exact scope,
retention, encryption, deletion route, and reviewer. Logs contain hashes,
dimensions, timing, and error classes rather than content.

## Failure criteria

- Raw pixels, clipboard values, audio, credentials, or native handles in normal
  logs, checkpoints, crash dumps, prompts, or learner history block release.
- A write without schema, provenance, retention, or atomicity evidence fails.
- Deletion that leaves undisclosed derived copies fails the retention contract.

## Focused spike

The synthetic fixture manifest proves that test inputs have an explicit root and
rights policy. Data lifecycle code and deletion fault injection belong to the
packets that introduce retained tutor state.

## Reversal

Stop new tutor writes, retain readable versioned records for governed export or
deletion, and remove projections only after their append records reconcile.
