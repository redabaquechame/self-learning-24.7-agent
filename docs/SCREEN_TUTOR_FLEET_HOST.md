# Fleet and the local Screen Tutor companion

This is a local integration candidate, not an installed or released product qualification. Fleet owns authentication, device assignment, the source approval, the provider account and the budget. The companion supplies a selected-source receipt. It cannot grant itself sharing permission.

Without explicit host configuration, the Screen Tutor card says the local companion is unavailable. It does not discover credentials and enable a provider automatically. Fleet's existing Learn/training pursuits remain separate from human learning sessions. Both use the shared learning.v1 contract where implemented; explanation is not evidence of a learning outcome.

## Explicit host configuration

Run the local Fleet panel with `--tutor-config` pointing to a host-owned JSON file. The file is configuration for the operator, not a browser upload. The panel must bind only to loopback. Configuration validates the executable candidate and declared image/provider accounting before advertising availability. Configuration alone launches no companion, captures no source and makes no model request.

Example structure (replace every example value with the intended host configuration):

```json
{
  "expert": "example-expert",
  "device_actor": "owner@example.com",
  "native_executable": "C:/installed-candidate/ScreenTutor.exe",
  "provider": "declared-provider",
  "model": "declared-model",
  "source_profile": {
    "profile_revision": "profile-1",
    "purpose": "source-explanation",
    "retention_policy_id": "retention-1",
    "budget_policy_id": "budget-policy-1",
    "budget_reservation_id": "reservation-1",
    "budget_ceiling_usd": 1.0,
    "provider_models": {"declared-provider": "declared-model"}
  }
}
```

The expert's existing settings must explicitly declare that same image provider/model in exactly one role, PNG support, image input units, bounded output and complete usage accounting/pricing. No example budget or provider is a recommendation or a default. The existing metered image gateway enforces the actual request's reservation and current account. The native executable must retain its verified candidate files; replacing them requires reconfiguration. This does not prove installer signing or production provider qualification.

The authenticated member must match `device_actor` and have the existing `run` permission for the expert. A remote/shared member is not silently treated as the owner of this desktop. Current bearer-token, role, expert path, executable candidate, source profile and account changes refuse or retire the original runtime. Its learning service is shared across companion sessions in that Fleet process; durable recovery is still a separate open gate.

## User journey

1. Open the expert's Overview and use **Open Screen Tutor**. Your Fleet page remains on the same expert/task context.
2. Choose a source in the companion. While approval is pending, it remains selected but unshared: no frames, image export or provider work begins.
3. Review the exact source-sharing request in Fleet's existing approval card. An actor with the existing `approve` permission can grant or deny it.
4. After approval, explicitly use **Retry authorization** in the companion. It retries the same selected source and original approval lifetime; waiting and retries do not renew that lifetime.
5. Ask about the current source. A configured image request remains subject to current account, source, role and metered budget checks. It does not grant computer actions, private-source research, or human assessment credit.
6. **Stop sharing** retires the source. **Close and return to Fleet** closes the companion. **Stop companion** in Fleet stops its owned child. Exit/server teardown retires source authority. A late approval after Stop cannot restart sharing.

Fleet marks earlier requests as retired or unavailable after Stop, replacement,
expiry, runtime restart or loss of the original actor/profile authority. Those
requests have no decision buttons; a stale decision is refused without changing
the owner's recorded decision. Source request details are visible to the device
member who requested them and members with the existing approval permission.
Ordinary expert/tool approvals keep their existing behavior.

While the exact approved source is still current, an approver can use
**Withdraw sharing permission**. This retires that source's live authority and
the host stops sharing and suppresses pending answers. The original grant stays
in approval history; withdrawal is a separate attributable audit event. Granting
an approval never starts a pursuit or captures a source automatically.

Fleet routes are GET `/api/experts/<slug>/tutor`, POST `/api/experts/<slug>/tutor/launch`, and POST `/api/experts/<slug>/tutor/stop`. Mutations accept only an empty object, require same-origin checks and existing run permission, and derive the caller from authentication. Web requests cannot select identity, executable, account, model, source grant or budget.

## Evidence limits

Owned Windows tests cover pending/grant/deny/Stop, real capture and a metered loopback image answer. Separate real HTTP/native tests and browser controls cover launch/discovery/Stop without source capture. These are controlled local receipts. Real accounts/provider economics, exact desktop placement/overlay, human outcomes, curriculum, device/accessibility/audio, installation/update/recovery and buyer handover acceptance remain open. Both products remain unaccepted.
