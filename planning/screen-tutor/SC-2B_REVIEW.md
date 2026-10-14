# SC-2B tutoring policy and learner-evidence review

**Scope:** instructional intent and move selection, qualified source use, help
fading, diagnostic hypotheses, actor/help/exposure attribution, outcome scoring,
append-only learner events, correction projection and instruction-quality review.  
**Review dimensions:** security, correctness, performance, maintainability.  
**Current verdict:** locally verified and reviewed in the offline scope; real
content review and T040 human/native accessibility qualification remain open.

## Resolved findings

1. **A direct question could be trapped in a quiz loop.** `UNDERSTAND` selects one
   direct explanation and states that no response is required.
2. **An instructional mode could silently execute.** Every generated instruction
   has no execution request and passes the existing strict wire validator under
   Guide authority.
3. **Generated advice could lack provenance.** Exact instructions require a
   qualified pack, exact ACL/version route and bounded retrieval. The plan maps a
   bounded evidence ID to the full source/revision/excerpt/license record.
4. **A caller could forge history to reduce help.** The policy reads only the
   exact tenant/project/user append-only ledger and fades after two comparable
   independent, correct, unexposed outcomes.
5. **Correct task completion could be mistaken for learning.** Agent execution is
   not assessable. Hints, arrows, shared work and answer exposure remain assisted,
   even when the outcome rubric says correct.
6. **Accessibility support could be penalized.** Declared accommodation without
   answer help remains independence-eligible; it still makes no qualified human
   accessibility claim.
7. **Tutor error could become a durable learner judgment.** User/reviewer
   corrections append a new event and invalidate named earlier events while both
   remain inspectable.
8. **Click imitation could reject another correct method.** The reporting rubric
   independently recomputes the expected outcome and ignores route and method.
9. **Latency could become a cognitive profile.** Pause/silence records permit only
   `UNDETERMINED`; projections carry no intelligence, diagnosis or emotion value.
10. **A review label could claim efficacy.** Fixture and organization-authorized
    content rubrics return instruction-quality fields while efficacy and retention
    stay null. Unbound qualified-review labels refuse.

## Security assessment

- Ledger identities and paths are bounded, scoped and traversal-safe. Stored JSON
  rejects malformed, duplicate-key and non-finite records.
- Events are immutable and conflicting IDs refuse under a process-safe lock.
- Projections reject mixed learner scopes, duplicate IDs and corrections that
  precede or name unknown events.
- Exact advice cannot bypass pack review, source rights, ACL or version gates.

## Correctness assessment

- T033-T039 pass offline. T040's policy rule passes only as an offline witness;
  human/native accessibility qualification has not been performed.
- The assistance/exposure mutation makes the learner test fail, proving those
  conditions are load-bearing.
- Instruction-quality review stays separate from human-learning and retention
  evidence.

## Performance assessment

- Retrieval, history, event and projection sizes are bounded. Current ledger
  projection is linear in the user's event count, capped at 10,000 events.
- Policy selection uses local deterministic checks and creates no model or native
  request by itself.

## Maintainability assessment

- `tutor_policy.py` owns move selection and instruction review;
  `tutor_learner.py` owns immutable evidence and projection.
- The strict existing instruction wire record remains unchanged inside a separate
  plan envelope, preserving protocol validation.
- Tests are registered in the authoritative suite, evidence inventory, doctor and
  mutation harness.

## Evidence boundary

The offline policy and storage mechanisms are locally verified. Synthetic pack
and organization records exercise authority transitions but do not represent an
actual content review. T040 requires real human participants using assistive
technology in the native companion. No learning efficacy, retention, usability,
accessibility, deployment, release or market-superiority claim follows.
