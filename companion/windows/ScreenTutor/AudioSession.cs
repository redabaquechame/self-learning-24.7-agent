using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace ScreenTutor;

public enum TutorAudioOrigin { Microphone, Media, Assistant }
public enum TutorAudioDeviceState { Available, Disconnected }
public enum TutorAudioRequestState { Queued, Reserved, InFlight, Completed, Failed, Cancelled }

public sealed record TutorAudioEvent(string EventId, TutorAudioOrigin Origin,
    string Transcript, long SourceEpoch);

public sealed class TutorAudioRequest
{
    internal TutorAudioRequest(string requestId, string effectKey, string transcript,
        long generationEpoch, long sourceEpoch)
    {
        RequestId = requestId;
        EffectKey = effectKey;
        Transcript = transcript;
        GenerationEpoch = generationEpoch;
        SourceEpoch = sourceEpoch;
    }

    public string RequestId { get; }
    public string EffectKey { get; }
    public string Transcript { get; }
    public long GenerationEpoch { get; }
    public long SourceEpoch { get; }
    public TutorAudioRequestState State { get; internal set; } = TutorAudioRequestState.Queued;
    public int Attempts { get; internal set; }
    public string? ReservationId { get; internal set; }
    public long ReservedCostUnits { get; internal set; }
    public string? ResponseId { get; internal set; }
}

/// <summary>
/// Local audio state only. This type owns no microphone, speaker, network or
/// provider object. Adapters must obey its epochs and reservation decisions.
/// </summary>
public sealed class TutorAudioSession
{
    public const int MaxActiveRequests = 4;
    public const int MaxRequests = 32;
    public const int MaxAttempts = 2;
    private const int MaxTranscriptChars = 8_000;
    private static readonly Regex Identifier = new(
        "^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", RegexOptions.CultureInvariant);
    private readonly HashSet<string> _scopes;
    private readonly List<TutorAudioRequest> _requests = [];
    private bool _stopped;

    public TutorAudioSession(string sessionId, IEnumerable<string> scopes)
    {
        RequireIdentifier(sessionId, nameof(sessionId));
        SessionId = sessionId;
        _scopes = new HashSet<string>(scopes, StringComparer.Ordinal);
        if (_scopes.Count is <= 0 or > 3
            || _scopes.Any(scope => scope is not ("MICROPHONE" or "MEDIA" or "ASSISTANT_PLAYBACK")))
            throw new InvalidDataException("Audio scopes are invalid.");
    }

    public string SessionId { get; }
    public bool PushToTalkHeld { get; private set; }
    public bool PlaybackActive { get; private set; }
    public bool CaptionsEnabled => true;
    public bool TextFallbackAvailable => true;
    public bool IsStopped => _stopped;
    public TutorAudioDeviceState DeviceState { get; private set; } = TutorAudioDeviceState.Available;
    public long GenerationEpoch { get; private set; }
    public long SourceEpoch { get; private set; }
    public long PlaybackEpoch { get; private set; }
    public IReadOnlyList<TutorAudioRequest> Requests => _requests;

    public static TutorAudioEvent ParseEvent(ReadOnlyMemory<byte> payload)
    {
        if (payload.Length is <= 0 or > 64 * 1024)
            throw new InvalidDataException("Audio event bytes are outside bounds.");
        try
        {
            using var document = JsonDocument.Parse(payload,
                new JsonDocumentOptions { MaxDepth = 4 });
            var root = document.RootElement;
            RequireFields(root, "schema", "event_id", "origin", "transcript", "source_epoch");
            if (root.GetProperty("schema").GetString() != "tutor.audio-event/1")
                throw new InvalidDataException("Audio event schema is invalid.");
            var eventId = RequiredIdentifier(root.GetProperty("event_id"), "event_id");
            var transcript = RequiredText(root.GetProperty("transcript"), "transcript",
                MaxTranscriptChars);
            var epoch = root.GetProperty("source_epoch");
            if (!epoch.TryGetInt64(out var sourceEpoch) || sourceEpoch < 0)
                throw new InvalidDataException("Audio source epoch is invalid.");
            var origin = root.GetProperty("origin").GetString() switch
            {
                "MICROPHONE" => TutorAudioOrigin.Microphone,
                "MEDIA" => TutorAudioOrigin.Media,
                "ASSISTANT" => TutorAudioOrigin.Assistant,
                _ => throw new InvalidDataException("Audio origin is invalid."),
            };
            return new TutorAudioEvent(eventId, origin, transcript, sourceEpoch);
        }
        catch (InvalidDataException) { throw; }
        catch (Exception error) when (error is JsonException or InvalidOperationException)
        {
            throw new InvalidDataException("Audio event JSON is malformed.", error);
        }
    }

    public (string Disposition, bool ExecutionAuthorized) Observe(TutorAudioEvent item)
    {
        EnsureActive();
        EnsureCurrent(item);
        if (item.Origin == TutorAudioOrigin.Media && !_scopes.Contains("MEDIA"))
            throw new InvalidOperationException("Media audio scope is required.");
        var disposition = item.Origin switch
        {
            TutorAudioOrigin.Assistant => "IGNORED_SELF_AUDIO",
            TutorAudioOrigin.Media => "CONTEXT_ONLY",
            _ => "TRANSCRIPT_ONLY",
        };
        return (disposition, false);
    }

    public void PressToTalk()
    {
        EnsureActive();
        if (!_scopes.Contains("MICROPHONE"))
            throw new InvalidOperationException("Microphone audio scope is required.");
        if (DeviceState != TutorAudioDeviceState.Available)
            throw new InvalidOperationException("Microphone device is disconnected.");
        if (PushToTalkHeld) return;
        CancelObsolete();
        PushToTalkHeld = true;
    }

    public TutorAudioRequest ReleaseToSubmit(TutorAudioEvent item, string requestId)
    {
        EnsureActive();
        RequireIdentifier(requestId, nameof(requestId));
        if (!PushToTalkHeld)
            throw new InvalidOperationException("A held push-to-talk capture is required.");
        EnsureCurrent(item);
        if (item.Origin != TutorAudioOrigin.Microphone)
            throw new InvalidOperationException("Only current microphone audio may submit.");
        PushToTalkHeld = false;
        var existing = _requests.SingleOrDefault(request => request.RequestId == requestId);
        if (existing is not null) return existing;
        if (_requests.Count >= MaxRequests)
            throw new InvalidOperationException("The bounded audio history is full.");
        if (_requests.Count(request => request.State is TutorAudioRequestState.Queued
                or TutorAudioRequestState.Reserved or TutorAudioRequestState.InFlight)
            >= MaxActiveRequests)
            throw new InvalidOperationException("The bounded audio queue is full.");
        var digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
            $"{SessionId}:{requestId}:{SourceEpoch}"))).ToLowerInvariant()[..32];
        var created = new TutorAudioRequest(requestId, $"audio-{digest}",
            item.Transcript, GenerationEpoch, SourceEpoch);
        _requests.Add(created);
        return created;
    }

    public void Reserve(string requestId, string reservationId, long costUnits)
    {
        EnsureActive();
        RequireIdentifier(reservationId, nameof(reservationId));
        if (costUnits is <= 0 or > 1_000_000)
            throw new InvalidDataException("Reserved cost is outside bounds.");
        var request = Find(requestId);
        if (request.State == TutorAudioRequestState.Reserved
            && request.ReservationId == reservationId) return;
        if (request.State != TutorAudioRequestState.Queued)
            throw new InvalidOperationException("Only a queued request can be reserved.");
        request.ReservationId = reservationId;
        request.ReservedCostUnits = costUnits;
        request.State = TutorAudioRequestState.Reserved;
    }

    public void BeginDispatch(string requestId, string reservationId)
    {
        EnsureActive();
        RequireIdentifier(reservationId, nameof(reservationId));
        var request = Find(requestId);
        if (request.ReservationId != reservationId
            || request.State is not (TutorAudioRequestState.Reserved or TutorAudioRequestState.Queued))
            throw new InvalidOperationException("A matching accounting reservation is required.");
        if (request.State == TutorAudioRequestState.Queued && request.Attempts == 0)
            throw new InvalidOperationException("The first dispatch must be reserved.");
        if (request.Attempts >= MaxAttempts)
            throw new InvalidOperationException("Audio retries are exhausted.");
        if (request.GenerationEpoch != GenerationEpoch || request.SourceEpoch != SourceEpoch)
        {
            request.State = TutorAudioRequestState.Cancelled;
            throw new InvalidOperationException("The audio request is stale.");
        }
        request.Attempts++;
        request.State = TutorAudioRequestState.InFlight;
    }

    public void NetworkFailure(string requestId)
    {
        EnsureActive();
        var request = Find(requestId);
        if (request.State != TutorAudioRequestState.InFlight)
            throw new InvalidOperationException("Only an in-flight request can fail.");
        request.State = request.Attempts >= MaxAttempts
            ? TutorAudioRequestState.Failed : TutorAudioRequestState.Queued;
    }

    public void AcceptResponse(string requestId, string responseId, long generationEpoch)
    {
        EnsureActive();
        RequireIdentifier(responseId, nameof(responseId));
        var request = Find(requestId);
        if (request.State != TutorAudioRequestState.InFlight
            || generationEpoch != GenerationEpoch
            || request.GenerationEpoch != GenerationEpoch
            || request.SourceEpoch != SourceEpoch)
            throw new InvalidOperationException("The audio response is stale.");
        request.ResponseId = responseId;
        request.State = TutorAudioRequestState.Completed;
        PlaybackEpoch++;
        PlaybackActive = _scopes.Contains("ASSISTANT_PLAYBACK");
    }

    public void BargeIn()
    {
        if (_stopped) return;
        CancelObsolete();
    }

    public void SetScopes(IEnumerable<string> scopes)
    {
        EnsureActive();
        var next = new HashSet<string>(scopes, StringComparer.Ordinal);
        if (next.Count is <= 0 or > 3
            || next.Any(scope => scope is not ("MICROPHONE" or "MEDIA" or "ASSISTANT_PLAYBACK")))
            throw new InvalidDataException("Audio scopes are invalid.");
        CancelObsolete();
        _scopes.Clear();
        _scopes.UnionWith(next);
        SourceEpoch++;
        PushToTalkHeld = false;
    }

    public void DeviceChanged(TutorAudioDeviceState state)
    {
        EnsureActive();
        DeviceState = state;
        if (state == TutorAudioDeviceState.Disconnected)
        {
            CancelObsolete();
            PushToTalkHeld = false;
        }
    }

    public void Stop()
    {
        if (_stopped) return;
        CancelObsolete();
        PushToTalkHeld = false;
        _stopped = true;
    }

    private void CancelObsolete()
    {
        GenerationEpoch++;
        PlaybackEpoch++;
        PlaybackActive = false;
        foreach (var request in _requests.Where(request => request.State is
                     TutorAudioRequestState.Queued or TutorAudioRequestState.Reserved
                     or TutorAudioRequestState.InFlight))
            request.State = TutorAudioRequestState.Cancelled;
    }

    private TutorAudioRequest Find(string requestId)
    {
        RequireIdentifier(requestId, nameof(requestId));
        return _requests.SingleOrDefault(request => request.RequestId == requestId)
            ?? throw new InvalidOperationException("Audio request is unknown.");
    }

    private void EnsureCurrent(TutorAudioEvent item)
    {
        if (item.SourceEpoch != SourceEpoch)
            throw new InvalidOperationException("The audio event is stale.");
    }

    private void EnsureActive()
    {
        if (_stopped) throw new InvalidOperationException("Audio session is stopped.");
    }

    private static string RequiredIdentifier(JsonElement value, string name)
    {
        if (value.ValueKind != JsonValueKind.String)
            throw new InvalidDataException($"Audio {name} has the wrong type.");
        var text = value.GetString();
        RequireIdentifier(text, name);
        return text!;
    }

    private static string RequiredText(JsonElement value, string name, int maximum)
    {
        if (value.ValueKind != JsonValueKind.String)
            throw new InvalidDataException($"Audio {name} has the wrong type.");
        var text = value.GetString();
        if (string.IsNullOrWhiteSpace(text) || text.Length > maximum)
            throw new InvalidDataException($"Audio {name} is invalid.");
        return text.Trim();
    }

    private static void RequireIdentifier(string? value, string name)
    {
        if (value is null || !Identifier.IsMatch(value))
            throw new InvalidDataException($"Audio {name} is invalid.");
    }

    private static void RequireFields(JsonElement value, params string[] fields)
    {
        if (value.ValueKind != JsonValueKind.Object)
            throw new InvalidDataException("Audio event must be an object.");
        var expected = new HashSet<string>(fields, StringComparer.Ordinal);
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in value.EnumerateObject())
            if (!expected.Contains(property.Name) || !seen.Add(property.Name))
                throw new InvalidDataException("Audio event has an unknown or duplicate field.");
        if (!seen.SetEquals(expected))
            throw new InvalidDataException("Audio event is missing a field.");
    }
}
