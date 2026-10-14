using System.IO;
using System.Text.RegularExpressions;

namespace ScreenTutor;

public sealed record MediaTimelineBinding(string MediaId, string SourceRevision,
    string ContentSha256, long ContentEpoch, long TimelineEpoch,
    string TimelineFingerprint);

public sealed record CurrentApplicationBinding(string ObservationId,
    string SourceId, string SourceRevision, long CaptureEpoch,
    string GeometryRevision, string AppId, string AppVersion);

public sealed record CurrentSemanticTarget(string TargetId, string SourceId,
    string SourceRevision, string GeometryRevision, string Name, string Role,
    string Context, double X, double Y, double Width, double Height);

public sealed record MediaTransferResult(string Status, string Reason,
    CurrentSemanticTarget? CurrentTarget, bool TutorialCoordinatesUsed,
    bool LearnerSuccessClaimed, string PackId, string PackDigest,
    string ObservationId, long CaptureEpoch);

public sealed record PlaybackAuthority(string GrantId, string Actor,
    bool UserInitiated, string MediaId, string SourceRevision,
    long TimelineEpoch, long ExpiresAtMonotonicMs);

public sealed record PlaybackIntent(string Action, double? Value,
    string GrantId, string Actor, string MediaId, string SourceRevision,
    long TimelineEpoch, string Executor, bool Executed);

/// <summary>
/// Native data guard for timestamped explanations. It owns no decoder,
/// provider, screen reader, playback API or input injection capability.
/// </summary>
public static class MediaTutoringGuard
{
    private static readonly Regex Identifier = new(
        "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
        RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);
    private static readonly Regex Digest = new(
        "^[0-9a-f]{64}$",
        RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);

    public static MediaTimelineBinding ValidateBinding(MediaTimelineBinding value)
    {
        RequireIdentifier(value.MediaId, nameof(value.MediaId));
        RequireIdentifier(value.SourceRevision, nameof(value.SourceRevision));
        RequireDigest(value.ContentSha256, nameof(value.ContentSha256));
        RequireDigest(value.TimelineFingerprint, nameof(value.TimelineFingerprint));
        if (value.ContentEpoch < 0 || value.TimelineEpoch < 0)
            throw new InvalidDataException("media epochs are invalid");
        return value;
    }

    public static bool IsCurrent(MediaTimelineBinding explanation,
        MediaTimelineBinding current)
    {
        ValidateBinding(explanation);
        ValidateBinding(current);
        return explanation == current;
    }

    public static void RequireVisibleTransition(
        IReadOnlyList<(string FrameId, long TimestampMs)> frames)
    {
        if (frames.Count is < 2 or > 16
            || frames.Any(frame => !Identifier.IsMatch(frame.FrameId))
            || frames.Select(frame => frame.FrameId).Distinct(StringComparer.Ordinal).Count()
                != frames.Count
            || frames.Select(frame => frame.TimestampMs).Distinct().Count() < 2
            || frames.Any(frame => frame.TimestampMs < 0))
            throw new InvalidDataException(
                "visible transition requires distinct bounded before/after frame evidence");
    }

    public static MediaTransferResult BindCurrentApplication(
        MediaTimelineBinding explanationBinding,
        MediaTimelineBinding currentMedia,
        CurrentApplicationBinding currentApp,
        IReadOnlyList<CurrentSemanticTarget> candidates,
        string demonstratedGoal,
        string packId,
        string packDigest,
        bool packQualifiedBySubjectReviewer,
        string minimumAppVersion,
        string maximumAppVersion)
    {
        if (!IsCurrent(explanationBinding, currentMedia))
            throw new InvalidOperationException("stale media explanation");
        ValidateCurrentApp(currentApp);
        RequireIdentifier(packId, nameof(packId));
        RequireDigest(packDigest, nameof(packDigest));
        if (!packQualifiedBySubjectReviewer)
            throw new InvalidOperationException("media transfer pack is not qualified");
        if (string.IsNullOrWhiteSpace(demonstratedGoal)
            || demonstratedGoal.Length > 1_000)
            throw new InvalidDataException("demonstrated goal is invalid");
        if (!Version.TryParse(minimumAppVersion, out var minimum)
            || !Version.TryParse(maximumAppVersion, out var maximum)
            || !Version.TryParse(currentApp.AppVersion, out var current)
            || minimum > maximum || current < minimum || current > maximum)
            throw new InvalidOperationException("current application version is not qualified");
        if (candidates.Count > 128)
            throw new InvalidDataException("semantic candidate list exceeds bound");
        var terms = Regex.Matches(demonstratedGoal.ToLowerInvariant(), "[a-z0-9]+")
            .Select(match => match.Value).ToHashSet(StringComparer.Ordinal);
        var ranked = candidates.Select(candidate =>
        {
            ValidateTarget(candidate, currentApp);
            var words = Regex.Matches(
                    $"{candidate.Name} {candidate.Role} {candidate.Context}".ToLowerInvariant(),
                    "[a-z0-9]+")
                .Select(match => match.Value).ToHashSet(StringComparer.Ordinal);
            return (Target: candidate, Score: terms.Intersect(words).Count());
        }).Where(item => item.Score > 0)
          .OrderByDescending(item => item.Score)
          .ThenBy(item => item.Target.TargetId, StringComparer.Ordinal).ToArray();
        if (ranked.Length == 0 || (ranked.Length > 1 && ranked[0].Score == ranked[1].Score))
            return new MediaTransferResult("ABSTAIN",
                ranked.Length == 0 ? "TARGET_NOT_FOUND" : "AMBIGUOUS_SEMANTIC_TARGET",
                null, false, false, packId, packDigest,
                currentApp.ObservationId, currentApp.CaptureEpoch);
        return new MediaTransferResult("GROUNDED", "UNIQUE_SEMANTIC_TARGET",
            ranked[0].Target, false, false, packId, packDigest,
            currentApp.ObservationId, currentApp.CaptureEpoch);
    }

    public static PlaybackIntent RequestPlaybackIntent(
        MediaTimelineBinding explanationBinding,
        MediaTimelineBinding currentMedia,
        string action,
        double? value,
        PlaybackAuthority authority,
        long nowMonotonicMs,
        long durationMs)
    {
        if (!IsCurrent(explanationBinding, currentMedia))
            throw new InvalidOperationException("stale media explanation");
        RequireIdentifier(authority.GrantId, nameof(authority.GrantId));
        RequireIdentifier(authority.Actor, nameof(authority.Actor));
        if (!authority.UserInitiated || authority.MediaId != currentMedia.MediaId
            || authority.SourceRevision != currentMedia.SourceRevision
            || authority.TimelineEpoch != currentMedia.TimelineEpoch
            || authority.ExpiresAtMonotonicMs <= nowMonotonicMs)
            throw new InvalidOperationException("playback authority is absent, stale or expired");
        double? checkedValue = action switch
        {
            "PLAY" or "PAUSE" when value is null => null,
            "SEEK" when value is >= 0 && value <= durationMs => value,
            "RATE" when value is >= 0.25 and <= 4.0 => value,
            _ => throw new InvalidDataException("playback action or value is invalid"),
        };
        return new PlaybackIntent(action, checkedValue, authority.GrantId,
            authority.Actor, currentMedia.MediaId, currentMedia.SourceRevision,
            currentMedia.TimelineEpoch, "NONE_INTENT_ONLY", false);
    }

    private static void ValidateCurrentApp(CurrentApplicationBinding value)
    {
        RequireIdentifier(value.ObservationId, nameof(value.ObservationId));
        RequireIdentifier(value.SourceId, nameof(value.SourceId));
        RequireIdentifier(value.SourceRevision, nameof(value.SourceRevision));
        RequireIdentifier(value.GeometryRevision, nameof(value.GeometryRevision));
        RequireIdentifier(value.AppId, nameof(value.AppId));
        if (value.CaptureEpoch < 0 || !Version.TryParse(value.AppVersion, out _))
            throw new InvalidDataException("current application binding is invalid");
    }

    private static void ValidateTarget(CurrentSemanticTarget value,
        CurrentApplicationBinding current)
    {
        RequireIdentifier(value.TargetId, nameof(value.TargetId));
        if (value.SourceId != current.SourceId
            || value.SourceRevision != current.SourceRevision
            || value.GeometryRevision != current.GeometryRevision)
            throw new InvalidOperationException("semantic target is stale");
        if (string.IsNullOrWhiteSpace(value.Name) || string.IsNullOrWhiteSpace(value.Role)
            || value.Width <= 0 || value.Height <= 0
            || !double.IsFinite(value.X) || !double.IsFinite(value.Y)
            || !double.IsFinite(value.Width) || !double.IsFinite(value.Height))
            throw new InvalidDataException("semantic target is invalid");
    }

    private static void RequireIdentifier(string value, string name)
    {
        if (string.IsNullOrEmpty(value) || !Identifier.IsMatch(value))
            throw new InvalidDataException($"invalid {name}");
    }

    private static void RequireDigest(string value, string name)
    {
        if (string.IsNullOrEmpty(value) || !Digest.IsMatch(value))
            throw new InvalidDataException($"invalid {name}");
    }
}
