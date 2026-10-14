# SC-3A offline locale and audio-resilience review

**Scope:** candidate locale/glossary records, source-language and uncertainty
preservation, append-only caption corrections, code-switch spans, speech-rate
bounds, keyboard equivalents, visible fallback, device-change pause and
non-authoritative approval speech.  
**Review dimensions:** security, correctness, performance, maintainability.  
**Current verdict:** locally and natively verified for deterministic offline
contracts; packet acceptance remains blocked on every required external tier.

## Resolved findings

1. **An untranslated technical name could be fabricated.** `UNTRANSLATED`
   entries require a null preferred term and retain source spelling and refs.
2. **A candidate language could appear qualified.** Candidate records reject
   qualification refs. Qualified records need all four external refs, and
   runtime selection still requires those exact refs from a verifier.
3. **Caption cleanup could erase a recognition error.** Raw text and language
   spans are immutable; corrections append bounded revisions with actor/reason.
4. **Code switching could disappear into one language label.** Ordered spans
   must cover every raw character exactly once and retain each language tag.
5. **An accessibility preference could create unusable speech.** Speech rate is
   bounded from 0.5 to 2.0 and all four audio actions have unique keyboard paths.
6. **A replacement headset could silently keep recording.** Device change
   pauses capture, clears permission and increments a generation checked at
   reauthorization. The selective mutation that preserves capture is caught.
7. **Unknown quality could be reported as perfect zero error.** The unrun matrix
   requires null measurements and empty evidence tiers. Passed rows require all
   three tiers, a content digest and positive control results.
8. **Spoken or media approval could authorize an effect.** The X024B path
   composes with the SC-3 origin contract: neither media nor microphone text
   grants execution authority, including corrected or mistranscribed captions.

## Evidence

- X024A offline validates candidate fallback, source terminology, code-switch
  coverage, immutable raw captions, correction history, rate/input bounds and
  device reauthorization.
- X024B offline validates non-authoritative media/microphone approval and that
  unrun measurements remain unknown.
- The native witness repeats locale fallback, caption history, keyboard/rate
  bounds and device pause/reauthorization inside the compiled WPF assembly.
- The device-continuation mutation is caught by `test_tutor_locale.py`.

## Evidence boundary

SC-3A is not accepted. SC-3 and SC-2D remain unaccepted dependencies. No speech
provider, locale/accent corpus, microphone, speaker, headset, background-noise
or echo test ran. No subject-matter reviewer evaluated the glossary, no human
comprehension study ran, and no screen reader or other assistive technology was
used. The `en-CA` pack is explicitly `CANDIDATE`; every matrix measurement is
`null` and `NOT_RUN`. This review makes no production, release, deployment,
language-quality, accessibility-conformance or market-superiority claim.
