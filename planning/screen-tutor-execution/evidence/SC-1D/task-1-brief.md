## Task 1: Source-bound unknown-application explanations

Owned files: `tutor_investigation.py`, `tests/test_tutor_investigation.py`, `evaluation/tutor/unknown_apps/`.

Implement a host-scoped investigation service using the existing source registry. Identify the exact app/version; classify the question; retrieve permitted teaching material without requiring a pack. Build a bounded source map with immutable revision, excerpt digest, app range, rights and tenant/project identity. Distinguish observed facts, documentation quotes, user reports and hypotheses. Never infer screen coordinates from documentation. Missing or incompatible evidence yields a useful explanation of limits and the precise next evidence needed, not an invented target or citation.

Write failing behavior tests first. Test a frozen unseen app, foreign tenant/project, conflicting app versions, absent/private documentation, altered citation bytes, fabricated button location, inert hostile source instructions, current-observation provenance, cancellation/staleness and bounded results. Documentation quote checking is byte/span support, not semantic verification of arbitrary paraphrases.

Expected RED: the new investigation behavior is absent. Expected GREEN: real registry/contract paths return exact fixture evidence and refuse the named negative cases. No model, network or application action occurs in this source-only path.

