# Windows atomic write repair implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow File Authority to atomically write a valid Windows destination without its own scratch filename exceeding the path limit.

**Architecture:** Keep existing path/zone/actor admission and same-directory atomic replace. Text and binary paths use one private short-name exclusive staging helper preserving ordinary creation permissions under the process umask, retaining encoding, durable flush/fsync, retry semantics, concurrent whole-file publication and failure cleanup.

**Tech Stack:** Existing CPython3.12.13 standard library; secrets.token_urlsafe, exclusive os.open, os.fdopen, os.replace. No dependency or platform-setting changes.

**Spec:** Existing File Authority manual§19 and `docs/DESIGN-P6.1-correctness-hardening.md` finding6 (unique concurrent atomic staging); native-continuity final regression observed test_tutor_investigation.py failure. Raw FINAL_CAMPAIGN.json/full-final.log and PRACTICE_PATH_DIAGNOSIS.json preserve the failure and cause.

## Global constraints

- Current native-continuity campaign is terminal failed, not green:179 executed,175 passed,3 explicit skips,1 failed; all558 frozen source files unchanged. Preserve it, never overwrite/restart its handle38570.
- Keep File Authority containment, protected zones and actor rules unchanged; staging occurs only beside an already-authorized destination. Preserve public signatures and successful return paths.
- Exclusive scratch creation, same-volume atomic replacement, existing8 retry attempts plus final replace, durable text fsync and no partial publication remain required.
- Preserve original authored dirty work and all native review evidence. No system long-path policy change, private file access, provider, application input or release.
- This independently reviewable storage regression repair is necessary for the original platform; it does not replace the pending actual host/Ask/overlay/installed journey.

## Review focus

1. Concurrent writers must have exclusive distinct staging files and publish whole payloads; Task1 tests8 writers.
2. Failed replacement must leave the previous destination and clean uncommitted staging; Task1 injects EIO.
3. Invalid/default text encoding must preserve mode, the original error, descriptor ownership and previous content; Task1 pins encoding=None and invalid codec.
4. Short scratch creation must not bypass containment/zone rules or introduce cross-volume replacement; Task2 includes paths/hardening/protected baseline and reviewer checks admission order.
5. Durable writes must still fsync before replacement; Task1 exercises durable text and reviewer checks ordering; Task2 retains existing storage/transaction checks.

## Task 1: Reproduce and repair valid-path atomic publication

**Files:** `fileauth.py`; `tests/test_correctness_patch.py`.

**Interfaces:** Preserve write_text/write_bytes signatures. Private `_atomic_write(path, value, *, mode="wb", encoding=None, durable=False)` consumes an already-resolved path; creates a short exclusive same-directory file, explicitly owns/closes its descriptor, flushes/fsyncs when requested, retries atomic replace and removes uncommitted staging on failure.

- [x] Reproduce full-suite failure with the original long test root; run the unchanged short-root control. Expected: long root fails, short control passes. Native file probe proves valid243-character target write succeeds but286-character appended scratch fails; short same-directory scratch succeeds.
- [x] Write/run Windows regression for valid243-character binary/text target, durable/default/invalid text encoding,8 concurrent writers, failed replace retaining old bytes and cleanup. Observe atomic-path-red.log; then explicit text-mode and descriptor-ownership RED witnesses as the shared helper is refined.
- [x] Implement short exclusive staging with unchanged admission, encoding/text newline semantics, durable flush/fsync, retry and replace. Run test_correctness_patch.py and the original long-root tutor-investigation failure. Expected GREEN; no harness-root shortening as the fix.
- [ ] Commit reviewed owned files only after Task2 gate. Preserve unrelated staged/untracked work.

## Task 2: Independent review, affected checks and final candidate

- [ ] Run correctness, investigation, practice, hardening, paths, ledger-defect, transactional-contract and feature-off suites; inspect every real terminal result. Diff whitespace check must pass.
- [ ] Obtain one fresh review of this independent storage repair, its original Git baseline, diagnostics and witnesses. Native continuity already had its one review; do not re-review that package. Repair Important/Critical findings once with RED/GREEN; preserve Minors.
- [ ] Freeze the updated complete candidate and run the complete179-script normal suite once after material repair/review. Preserve prior failed campaign, all skips, exact hashes and new terminal result. A focused green test cannot change the failed campaign's verdict.
- [ ] Preserve review, source identities, raw logs, rollback (restore only the owned File Authority/test/plan changes) and checkpoint. Then continue the staged native-host/Ask plan; all original provider/content/native/human/release gates remain open.

## Execution chronology and ruling

This repair arose during the existing activated plan's final regression step. Root-cause diagnosis, RED tests and the minimal repair were performed immediately under that plan's authorized fix procedure; this independently reviewable supplement was written afterward to record the broadened core-file ownership and review gate. It is not represented as a pre-implementation plan. Cost of the deviation: the fresh storage reviewer must assess both shared writer semantics and all relevant compatibility evidence before the new full candidate is frozen. The original whole-platform plan and chosen inline execution method remain authoritative.

## Final review ruling

Fresh atomic_write_review found no confirmed issues in the initial repair and explicitly set POSIX permissions aside. The coordinator reproduced a compatibility regression in cached network-none Linux Python: baseline created0644 outputs under umask022, initial mkstemp candidate created0600. This was regraded Important and repaired in the single fix pass using short cryptographic names with exclusive os.open(...,0666), leaving umask enforcement to the OS without process-global mutation. POSIX022/077 permission, native Windows path/concurrency/descriptor and exclusive collision witnesses pass. No second reviewer is requested; the new complete frozen-candidate suite remains required.
