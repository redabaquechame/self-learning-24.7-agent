# Execution decisions

## ADR-001: Isolated implementation branch

**Status:** Accepted  
**Decision:** Build from current \`origin/main\` in \`codex/screen-tutor-build\`. Preserve the older local main and every existing dirty worktree.  
**Reason:** The plan baseline equals current remote main, while the local main is behind and other worktrees contain unrelated work.  
**Reversal:** Rebase or merge only after checking current remote and resolving any overlapping ownership.

## ADR-002: Immutable plan and separate live state

**Status:** Accepted  
**Decision:** Keep live execution records in this directory. Never regenerate them from the planning package.  
**Reason:** Planning generation intentionally resets its template state to NOT_STARTED.

## ADR-003: Stable isolated Windows toolchain

**Status:** Accepted  
**Decision:** Pin .NET SDK 10.0.401 with preview and roll-forward disabled, Windows App SDK 2.4.0, a NuGet dependency lock, and dependency license hashes. Use an isolated SDK when the machine-wide installation is unqualified.  
**Reason:** The host only exposes .NET 11 preview globally; selecting it would make builds non-reproducible and turn an observation into a supported default.

## ADR-004: Source archives exclude native products

**Status:** Accepted  
**Decision:** Ship companion source, `global.json`, and `packages.lock.json`; exclude `bin/` and `obj/`.  
**Reason:** Generated native DLLs are platform-specific build products and caused the package credential-shape scanner to fail on public-key metadata.

## ADR-005: One strict tutor protocol and one generated native fixture

**Status:** Accepted  
**Decision:** Keep `tutor_contracts.py` as the executable v1 schema, generate one canonical fixture from it, and make the optional native probe consume that fixture. Protocol validation views existing grants and never creates them.  
**Reason:** Two handwritten schemas drift, while model-visible grants or native handles would create an alternate authority path.  
**Reversal:** A future protocol major requires an explicit migration, downgrade fixtures and refusal behavior; it cannot silently reinterpret v1 fields.

## ADR-006: OS-selected capture with host authorization and bounded deep copies

**Status:** Accepted  
**Decision:** Use Windows Graphics Capture through the OS picker, create the D3D11/WinRT device through the documented interop path, and keep selection separate from pixel authorization. Bind each frame to an opaque source ID, source revision and capture epoch; deep-copy at most three BGRA frames into a 64 MiB transient queue and overwrite owned buffers on every invalidating transition. Run structural observation on a separate background MTA worker with a deadline and immediate non-joining Stop.  
**Reason:** Native handles and display names are weak authority, selection is not consent to start collection, and UIA providers may hang. The capture path must fail closed without following focus, persisting raw pixels or freezing local Stop.  
**Qualification:** A real test-owned Windows source and synthetic fault fixtures pass. The private picker journey, OS permission UI, process-crash, signed installer and driver/device matrix remain later gates.
