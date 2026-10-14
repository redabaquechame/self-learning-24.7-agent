# Highlight integration decision

**Decision:** `ADAPTER_ABSENT_PLATFORM_OWNED_CONTEXT_SHIPS_INDEPENDENTLY`  
**Evidence checked:** 2026-09-15  
**Vendor:** Highlight AI (`highlightai.com`)

## Current primary-source findings

1. Highlight's current privacy page says its product continuously observes the
   screen, permits application/site/window exclusions, stores an encrypted copy
   of transcripts in its database, stores meeting notes/chat in Supabase, and
   stores its context engine in Google Cloud object storage. It also says raw
   audio is discarded after transcription and users can delete data from
   Settings. Source: [Highlight Privacy](https://highlightai.com/privacy),
   inspected 2026-09-15.
2. Highlight's current Connections page says connections are powered by Model
   Context Protocol and lets users add custom plugins to connect and update apps
   from within Highlight. That establishes a route for tools to connect to the
   Highlight product. It does not document a supported API for embedding
   Highlight's private desktop context inside this platform. Source:
   [Highlight Connections](https://highlightai.com/connections), inspected
   2026-09-15.
3. The old developer path redirects to a documentation home whose navigation
   describes using the Highlight assistant, interfaces, plugins, shortcuts and
   attachments. I did not find a maintained authentication, endpoint, scope,
   webhook, export, deletion, rate-limit, versioning or commercial embedding
   contract. Source: [Highlight Developer Docs](https://docs.highlightai.com/welcome),
   inspected 2026-09-15.
4. Highlight's terms, last updated 2026-04-16, describe a limited,
   non-transferable, non-sublicensable, revocable license and say the service is
   for personal use unless Highlight expressly authorizes commercial use. The
   terms mention public content through APIs but do not grant this project a
   private-context embedding right. Source:
   [Highlight Terms](https://highlightai.com/terms), inspected 2026-09-15.

## Result

No Highlight adapter will be created from guessed private endpoints, UI
automation, reverse engineering, exported session databases or user credentials.
The core Screen Tutor context interface remains platform-owned and complete when
Highlight is absent, unavailable or removed.

The product patterns worth retaining are explicit context attachment, useful
cross-application continuity, application exclusions and staged actions. This
implementation uses selected context and separate capture/transmit/retain scopes;
it does not adopt continuous observation as the default.

## Conditions for reconsideration

Reconsider only when Highlight or an authorized commercial agreement supplies a
current, versioned integration contract covering:

- private-context read/export endpoints and authentication;
- least-privilege scopes and tenant/account isolation;
- capture, transmit, retention, deletion and revocation behavior;
- data destinations, subprocessors and model-training terms;
- commercial embedding/licensing rights;
- rate limits, pricing, support and deprecation policy;
- correlated test credentials and a revocation/deletion sandbox.

Even then, the adapter must remain optional. Removing it must revoke its context
handles without disabling selected files, messages, meetings, screen context,
drafts, goals or the core companion.
