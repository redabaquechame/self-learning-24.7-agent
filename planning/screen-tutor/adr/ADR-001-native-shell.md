# ADR-001: Windows native companion shell

**Status:** Accepted for implementation  
**Decision date:** 2026-09-14

## Context

The companion must summon quickly, capture only the user-selected scope, draw
anchored explanations over desktop applications, remain keyboard and screen
reader operable, and fail closed when Windows capabilities are unavailable.
The existing Python platform must continue to run without a Windows SDK.

## Decision

Build the Windows shell in C# on .NET 10 LTS with WinUI 3 from Windows App SDK
2.4.0. Pin the SDK through `companion/windows/global.json`. Keep native projects
under `companion/windows/`; do not add a root Python dependency manifest.

The shell owns windows, overlays, selection UI, capture consent, DPI transforms,
and Windows capability discovery. It does not own tutoring policy, model routing,
durable evidence, authority decisions, or learner history. Use `AppWindow` and
documented Win32 interop only where WinUI has no equivalent. A capability probe
must classify each capture, overlay, input, audio, and accessibility primitive as
AVAILABLE, DEGRADED, DENIED, or UNKNOWN before use.

## Failure criteria

- A preview SDK, roll-forward SDK, unsigned production package, or undeclared
  native dependency makes the native lane unqualified.
- Missing capture permission, protected content, mixed-DPI transform evidence,
  or accessibility semantics disables the affected capability visibly.
- Native shell failure must not prevent the stdlib core from starting.

## Focused spike

`companion/windows/environment-probe` restores Windows App SDK 2.4.0, compiles
against its declared package graph, and runs on the pinned .NET runtime. It proves dependency resolution and compilation only;
it is not a UI, capture, packaging, device, or release qualification.

## Reversal

Remove the optional companion subtree and its adapter registration. Core state
and mission artifacts remain readable because the shell owns no durable truth.
