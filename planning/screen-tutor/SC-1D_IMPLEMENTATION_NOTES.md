# SC-1D current implementation and qualification boundary

The host can investigate an unfamiliar app without assigning a teaching pack.
`Investigation` binds the current tenant, project, app/version, cancellation
generation and explanation permission. It produces exact documentation quotes,
separately labelled observation metadata, user reports and hypotheses. It never
derives a screen target or application action from documentation. Quotation
support proves source agreement; it does not certify arbitrary paraphrases or
the truth of a vendor's documentation.

## Host-authorized document acquisition

`SourceAcquisition(home, current_state, current_policy).acquire(document_key)`
accepts a key from the current host policy, rather than a caller URL or path.
Host state must currently permit explanation and have
`document_acquisition_permitted` exactly true. This host permission is separate
from the existing closed v1 `grant_view` mode-capability vocabulary.

Policy contains exact `scope` and `recipes` fields. Scope is the five current
investigation identity/app/generation fields. A recipe binds kind (`local` or
`url`), exact locator, exact redirect allowlist, optional raw-byte SHA-256 pin,
format (`text` or `html`), source-registry metadata without revision/excerpts,
one approved line range and excerpt ID. The host owns source type, rights,
license and app-version range; a retrieved page cannot declare itself official
or grant access. The approved range refers to decoded UTF-8 text lines, or the
existing HTML text extractor's output, and must fit licensed ranges.

The adapter uses existing File Authority containment/secret checks and ingest
scheme/host checks. Redirects require both exact policy approval and fresh host
authority. The HTTP reader uses no ambient proxy, cookie jar, credentials or
application session. Payloads are capped at 128 KiB, redirects at five, and each
HTTP operation has a ten-second timeout. Compressed, non-UTF-8 and other formats
refuse pending explicit adapters; the core's general ingestion capabilities
are not automatically qualified for Tutor investigation.

Raw bytes derive an immutable source revision, while the selected excerpt has
its own digest. An optional pin refuses drift; an unpinned approved document
creates a new digest-derived revision. Only the approved excerpt enters the
teaching registry. The returned provenance receipt includes effective locator,
raw digest, registry digest and exact policy digest. There is no background
crawl, downloaded-code execution or automatic promotion to reviewed content.

## Reversible examples

`ReversibleSamples(investigator, current_policy)` creates a disposable example
only when current host state has `sample_practice_permitted` exactly true and
its policy binds the exact user, investigation scope, documentation citation,
synthetic/licensed source and existing practice specification. The citation
must support the current explanation. Production documents decline.

The existing `tutor_practice` copy/check/reset mechanisms remain the executor.
This route supports assisted deterministic JSON examples; independent exams,
subjective grading, qualified assignment/pack binding and real-app gestures
remain separate requirements. A host-supplied pack label cannot qualify a pack.
Every created copy gets a unique internal practice ID. Callers receive an opaque
handle and artifact path, never an editable answer key or verifier session.

`verify(handle)` independently checks the current generated artifact;
`reset(handle)` restores the source bytes after integrity/authority checks;
`stop(handle)` remains local and available after permission revocation. Stopped
handles free active capacity while a bounded tombstone list prevents immediate
replay. Source changes, answer-key revisions, identity/app changes, policy
revocation and forged handles refuse. An artifact pass is mechanically scoped
and never creates independent learning success.

## Existing service integration

`TutorService.investigate` retains its feature/session/request/observation
admission gates. Optional host-selected `source_keys` and `acquirer` acquire
approved documentation before explanation. Optional `sample_key` and `samples`
deliver a reversible example under explicit host policy. Each retrieval stage
and final release recheck the actual selected-source session. Sample authority
and app/version scope are checked separately at release; revoked examples are
stopped and omitted. Corrupt registry input produces a bounded refusal.

This is backend integration. The native visible Ask button, authenticated user
document/sample selection and production overlay journey are not wired by this
packet. None of the local fixtures proves live model correctness, independent
content review, real-app performance or human learning. SC-1D stays unaccepted
until its original required tiers and full journey criteria are satisfied.
