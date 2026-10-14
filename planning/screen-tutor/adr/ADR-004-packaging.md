# ADR-004: Windows packaging, update, and rollback boundary

**Status:** Accepted for implementation  
**Decision date:** 2026-09-14

## Context

The companion requires Windows capabilities, reliable identity, clean removal,
and reversible updates. A developer executable does not prove installability or
production readiness.

## Decision

Ship the production Windows companion as a signed, per-user MSIX package with a
declared Windows App SDK framework dependency. Produce an offline enterprise
bundle only when it carries the exact signed framework dependency and licenses.
Keep an unpackaged build for local development and native tests; label it
UNQUALIFIED_FOR_RELEASE. Pin package identity, publisher, capabilities, protocol
version, minimum OS, signing certificate lineage, SBOM, and artifact hashes in
the release packet.

Use staged rollout with health checks, last-known-good package retention, schema
compatibility across one rollback version, and an explicit disable switch for
capture and interaction. Updates never bypass user or institution policy.

## Failure criteria

- Unsigned, expired, identity-mismatched, non-reproducible, or unscanned output
  cannot enter a release channel.
- Install, update, downgrade, uninstall, crash-recovery, and data-preservation
  tests must run on clean supported Windows devices before release.
- An unpackaged developer run cannot satisfy NATIVE or RELEASE evidence.

## Focused spike

The environment probe is deliberately unpackaged and validates restore/build/run
only. Signing, MSIX generation, update, soak, and rollback are owned by the
release and operations packets.

## Reversal

Disable the release channel, roll back to the last compatible signed package,
and preserve reconciled core records. Revoke affected signing material through
the release runbook if integrity is in doubt.
