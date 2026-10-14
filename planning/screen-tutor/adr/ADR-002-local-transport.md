# ADR-002: Authenticated local companion transport

**Status:** Accepted for implementation  
**Decision date:** 2026-09-14

## Context

The native shell and Python service need a local boundary that does not expose
screen data on a network port or let another desktop process issue actions.

## Decision

Use a per-user Windows named pipe owned by the native broker. Apply an ACL for
the launching user and LocalSystem, generate a 256-bit session secret for every
launch, and require a mutual versioned handshake before accepting messages.
Frames are length-prefixed UTF-8 canonical JSON with a maximum declared size,
monotonic sequence number, correlation ID, deadline, cancellation ID, and typed
payload schema. Reject duplicate, expired, oversized, unknown-version, or
out-of-order messages before dispatch. Transfer images through bounded shared
memory referenced by opaque single-use handles; never serialize raw pixels into
logs or durable messages.

The Python adapter can request operations but every effect still passes through
the existing Execution, File, Credential, Model Gateway, and Effect authorities.
The pipe is not an authority and cannot broaden a grant.

## Failure criteria

- A TCP listener, world-readable pipe, reusable session secret, raw native
  handle in durable storage, or unbounded frame is a release-blocking defect.
- Failed identity, handshake, schema, deadline, or sequence validation closes
  the connection and records metadata without payload content.
- Transport loss cancels uncommitted actions and reconciles committed effects.

## Focused spike

The environment probe establishes only that the pinned native toolchain can
compile. SC-0B must encode and fuzz the handshake, frame, cancellation, replay,
and authority contracts before the transport is implemented.

## Reversal

Disable companion registration and close the pipe. Preserve existing durable
mission and effect records; discard the ephemeral session secret and buffers.
