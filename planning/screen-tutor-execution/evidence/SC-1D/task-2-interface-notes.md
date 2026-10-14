# SC-1D Task 2 interface findings

Read during the frozen Task 1 whole-suite campaign; no product source changed.

- TutorService.ask already authorizes the request, checks exact requested observations, checks cancellation before provider dispatch, and validates the returned instruction. Investigation integration must use these same boundaries and current session identity/source bindings.
- Observation validation requires the current host identity/consent/source revision/capture epoch and expiry, not only an observation ID. A source switch or Stop during retrieval must suppress release even if the returned documentation quotation is otherwise valid.
- Ingest.fetch_url already checks allowed schemes, destinations and redirects, but its legacy intake is broad and its destination writes are outside the file-authority helper. New investigation acquisition must resolve its owned destination through file authority and preserve exact fetched-byte/source provenance; caller text must not grant an origin, filesystem scope or official-source label.
- httpstate is a closed owner-endpoint JSON adapter that refuses redirects/non-JSON responses. It is not a general official-documentation HTML downloader, so reusing it without an explicit scope decision would silently narrow the packet.
- Reversible samples must call the existing tutor_practice source/digest/watch/verify/reset contract. No new shell executor or model-decided success is permitted. Ordinary application actions remain outside the explanation boundary.
- Real source/provider/content qualification and the installed visible companion journey are separate acceptance tiers. Local fixture witnesses will not close them.
