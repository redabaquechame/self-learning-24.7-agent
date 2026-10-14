# ADR-009: Transparent instructional policy and learner evidence

**Status:** Accepted for implementation  
**Decision date:** 2026-09-15

## Context

Task completion and learning are different outcomes. Explicit arrows, revealed
answers and agent execution can produce a correct artifact without independent
learner evidence. A wrong app version or tutor instruction can also create a
failure that must not become a judgment about the learner. Accessibility support
must remain available without being confused with answer-revealing help.

## Decision

Keep Explain/Guide/Collaborate/Delegate authority separate from the user's
Understand/Finish/Learn/Assess intent. Select exactly one instructional move from
a qualified pack and its scoped sources. Answer direct questions directly. Fade
help only after comparable independent, correct, unexposed outcomes read from the
exact learner's durable ledger.

Record exposure, attempt, correction and pause/silence observation events in an
append-only tenant/project/user ledger. Attribute actor and assistance explicitly.
Agent execution is not assessable; hints/arrows and answer exposure are assisted;
non-answer-revealing accommodation remains independence-eligible. Rebuild the
projection from raw events. A later correction invalidates dependent judgments
while retaining both records. Score task outcomes independently of click route or
method. Keep instruction-quality review, human learning, retention and operational
utility as separate evidence fields.

## Failure criteria

- A correct assisted, exposed or agent-performed result increments independent
  learner evidence.
- Caller-supplied history, another tenant, or another user changes help fading.
- A pause or silence becomes a diagnosis, intelligence, personality or emotion
  inference.
- Correcting tutor/version error deletes history or leaves a dependent learner
  judgment valid.
- Accessibility accommodation alone makes an attempt assisted.
- Passing policy or rubric tests creates a human-learning or retention claim.

## Reversal

Disable adaptive help selection and serve direct qualified source explanations.
Preserve the append-only evidence ledger and correction history; rebuild a flat
projection with every attempt marked unscored until the policy is restored.
