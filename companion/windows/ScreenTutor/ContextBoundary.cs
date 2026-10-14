using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace ScreenTutor;

public enum ContextKind
{
    File,
    Message,
    Meeting,
    Screen,
}

public sealed record ContextSource(
    string ItemId,
    ContextKind Kind,
    string OriginRef,
    string UserId,
    string AccountId,
    string TenantId,
    string ProjectId,
    string SourceRevision,
    string ContentSha256,
    DateTimeOffset ObservedAtUtc,
    bool AccessPermitted,
    bool DeletionEligible,
    string Content,
    bool UserSelected);

public sealed record NativeContextItem(
    ContextSource Source,
    long AttachedGeneration,
    string Status,
    string? DetachedReason,
    bool InstructionsExecutable,
    string Authority);

public sealed record NativeContextView(
    string SessionId,
    long Generation,
    string UserId,
    string AccountId,
    string TenantId,
    string ProjectId,
    IReadOnlyList<NativeContextItem> Items,
    string? Draft,
    string? Goal,
    bool ConnectorPresent,
    bool GlobalCaptureEnabled);

/// <summary>
/// Native companion boundary for explicit context attachment. This class has
/// no connector, observer, network, model or screen-capture capability.
/// </summary>
public sealed class NativeContextSession
{
    private static readonly Regex Identifier = new(
        "^[A-Za-z0-9][A-Za-z0-9_.@-]{0,255}$",
        RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);
    private static readonly Regex Digest = new(
        "^[0-9a-f]{64}$",
        RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);
    private readonly HashSet<ContextKind> _capture;
    private readonly HashSet<ContextKind> _transmit;
    private readonly HashSet<ContextKind> _retain;
    private readonly Dictionary<string, NativeContextItem> _items =
        new(StringComparer.Ordinal);
    private bool _closed;

    public NativeContextSession(string sessionId, string userId,
        string accountId, string tenantId, string projectId,
        IEnumerable<ContextKind> capture, IEnumerable<ContextKind> transmit,
        IEnumerable<ContextKind> retain)
    {
        SessionId = RequireIdentifier(sessionId, nameof(sessionId));
        UserId = RequireIdentifier(userId, nameof(userId));
        AccountId = RequireIdentifier(accountId, nameof(accountId));
        TenantId = RequireIdentifier(tenantId, nameof(tenantId));
        ProjectId = RequireIdentifier(projectId, nameof(projectId));
        _capture = BoundedKinds(capture, nameof(capture));
        _transmit = BoundedKinds(transmit, nameof(transmit));
        _retain = BoundedKinds(retain, nameof(retain));
    }

    public string SessionId { get; }
    public string UserId { get; }
    public string AccountId { get; private set; }
    public string TenantId { get; private set; }
    public string ProjectId { get; private set; }
    public long Generation { get; private set; }
    public string? Draft { get; private set; }
    public string? Goal { get; private set; }

    public NativeContextItem Attach(ContextSource source)
    {
        RequireActive();
        ValidateSource(source);
        if (!source.UserSelected)
            throw new InvalidOperationException("explicit context selection is required");
        if (!source.AccessPermitted)
            throw new InvalidOperationException("context access is revoked");
        if (!_capture.Contains(source.Kind))
            throw new InvalidOperationException("context capture scope denied");
        if (source.UserId != UserId || source.AccountId != AccountId
            || source.TenantId != TenantId || source.ProjectId != ProjectId)
            throw new InvalidOperationException("context identity scope denied");
        if (_items.TryGetValue(source.ItemId, out var existing))
        {
            if (existing.Source == source && existing.Status == "ATTACHED")
                return existing;
            throw new InvalidOperationException("context identity conflicts with history");
        }
        if (_items.Count >= 128)
            throw new InvalidOperationException("context attachment limit reached");
        var stored = new NativeContextItem(source, Generation, "ATTACHED", null,
            false, "UNTRUSTED_CONTEXT_DATA");
        _items.Add(source.ItemId, stored);
        return stored;
    }

    public NativeContextItem Remove(string itemId, string reason = "USER_REMOVED")
    {
        RequireActive();
        RequireIdentifier(itemId, nameof(itemId));
        if (!_items.TryGetValue(itemId, out var stored)
            || stored.Status != "ATTACHED")
            throw new InvalidOperationException("context is not attached");
        var removed = stored with
        {
            Source = RemoveContent(stored.Source),
            Status = "DETACHED",
            DetachedReason = reason,
        };
        _items[itemId] = removed;
        Generation += 1;
        return removed;
    }

    public void SetContinuity(string? draft, string? goal)
    {
        RequireActive();
        Draft = RequireOptionalText(draft, 8_000, nameof(draft));
        Goal = RequireOptionalText(goal, 2_000, nameof(goal));
    }

    public NativeContextView CurrentView()
    {
        RequireActive();
        var visible = _items.Values
            .Where(item => item.Status == "ATTACHED"
                           && _transmit.Contains(item.Source.Kind))
            .OrderBy(item => item.Source.ItemId, StringComparer.Ordinal)
            .ToArray();
        return new NativeContextView(SessionId, Generation, UserId, AccountId,
            TenantId, ProjectId, visible, Draft, Goal, false, false);
    }

    public bool IsCurrent(NativeContextView view)
    {
        RequireActive();
        return view == CurrentView()
            || (view.SessionId == SessionId && view.Generation == Generation
                && view.UserId == UserId && view.AccountId == AccountId
                && view.TenantId == TenantId && view.ProjectId == ProjectId
                && view.Items.SequenceEqual(CurrentView().Items)
                && view.Draft == Draft && view.Goal == Goal
                && !view.ConnectorPresent && !view.GlobalCaptureEnabled);
    }

    public void SwitchAccount(string accountId, string tenantId, string projectId)
    {
        RequireActive();
        AccountId = RequireIdentifier(accountId, nameof(accountId));
        TenantId = RequireIdentifier(tenantId, nameof(tenantId));
        ProjectId = RequireIdentifier(projectId, nameof(projectId));
        foreach (var pair in _items.ToArray())
        {
            if (pair.Value.Status == "ATTACHED")
                _items[pair.Key] = pair.Value with
                {
                    Source = RemoveContent(pair.Value.Source),
                    Status = "DETACHED",
                    DetachedReason = "ACCOUNT_SWITCH",
                };
        }
        Generation += 1;
    }

    public void Close()
    {
        if (_closed)
            return;
        foreach (var pair in _items.ToArray())
        {
            if (!_retain.Contains(pair.Value.Source.Kind))
                _items[pair.Key] = pair.Value with
                {
                    Source = RemoveContent(pair.Value.Source),
                    Status = "DETACHED",
                    DetachedReason = "RETENTION_SCOPE_ENDED",
                };
        }
        _closed = true;
    }

    private static ContextSource RemoveContent(ContextSource source)
    {
        return source with
        {
            Content = "[removed]",
            ContentSha256 = Convert.ToHexString(
                SHA256.HashData(Encoding.UTF8.GetBytes("[removed]"))).ToLowerInvariant(),
        };
    }

    private static void ValidateSource(ContextSource source)
    {
        RequireIdentifier(source.ItemId, nameof(source.ItemId));
        RequireIdentifier(source.OriginRef, nameof(source.OriginRef));
        RequireIdentifier(source.UserId, nameof(source.UserId));
        RequireIdentifier(source.AccountId, nameof(source.AccountId));
        RequireIdentifier(source.TenantId, nameof(source.TenantId));
        RequireIdentifier(source.ProjectId, nameof(source.ProjectId));
        RequireIdentifier(source.SourceRevision, nameof(source.SourceRevision));
        if (!Digest.IsMatch(source.ContentSha256)
            || source.ObservedAtUtc.Offset != TimeSpan.Zero
            || string.IsNullOrWhiteSpace(source.Content)
            || source.Content.Length > 32_000
            || Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(source.Content)))
                .ToLowerInvariant() != source.ContentSha256)
            throw new InvalidDataException("context source content or provenance is invalid");
    }

    private static HashSet<ContextKind> BoundedKinds(
        IEnumerable<ContextKind> values, string name)
    {
        var result = values.ToHashSet();
        if (result.Count > Enum.GetValues<ContextKind>().Length)
            throw new InvalidDataException($"invalid {name}");
        return result;
    }

    private static string RequireIdentifier(string value, string name)
    {
        if (string.IsNullOrEmpty(value) || !Identifier.IsMatch(value))
            throw new InvalidDataException($"invalid {name}");
        return value;
    }

    private static string? RequireOptionalText(string? value, int maximum,
        string name)
    {
        if (value is null)
            return null;
        if (string.IsNullOrWhiteSpace(value) || value != value.Trim()
            || value.Length > maximum)
            throw new InvalidDataException($"invalid {name}");
        return value;
    }

    private void RequireActive()
    {
        if (_closed)
            throw new InvalidOperationException("context session is closed");
    }
}
