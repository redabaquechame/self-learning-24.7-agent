using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace ScreenTutor;

/// <summary>A verified established-peer envelope consumed in order but too old to apply.</summary>
public sealed class StaleBridgeMessageException : IOException
{
    public StaleBridgeMessageException() : base("Stale generation or expired authenticated message discarded.") { }
}

/// <summary>Per-launch mutual peer proof and ordered state. Owns no UI or IO locks.</summary>
public sealed class BridgePeer : IDisposable
{
    private readonly byte[] _key;
    private readonly string _sessionId;
    private readonly long _epoch;
    private readonly string _peer;
    private readonly string _protocolVersion;
    private readonly string _challenge = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
    private readonly object _gate = new();
    private readonly Queue<(long Sequence, string Digest)> _history = new();
    private string _phase = "NEW";
    private string? _remoteChallenge;
    private string? _handshakeReply;
    private long _sent;
    private long _received;
    private long _cancellationGeneration = 0;
    private readonly Dictionary<string, (string Kind, long Deadline)> _pendingSent = new(StringComparer.Ordinal);
    private readonly Dictionary<string, (string Kind, long Deadline)> _pendingReceived = new(StringComparer.Ordinal);
    private static readonly Dictionary<string, string> Replies = new(StringComparer.Ordinal) { ["ASK"] = "ANSWER", ["QUESTION"] = "ANSWER", ["SELECT_SOURCE"] = "CAPTURE_AUTHORIZATION", ["FRAME"] = "FRAME_ACCEPTED", ["PRACTICE_REQUEST"] = "PRACTICE_RESULT" };
    public bool Ready { get { lock (_gate) return _phase == "READY"; } }
    public int AcceptedHistoryCount { get { lock (_gate) return _history.Count; } }

    public BridgePeer(byte[] key, string sessionId, long epoch, string peer)
        : this(key, sessionId, epoch, peer, "1.1") { }

    public BridgePeer(byte[] key, string sessionId, long epoch, string peer, string protocolVersion)
    {
        if (protocolVersion is not ("1.1" or "1.2")) throw new InvalidDataException("Unsupported bridge version.");
        _protocolVersion = protocolVersion;
        if (key.Length < 32 || !Regex.IsMatch(sessionId, "^[A-Za-z0-9_-]{1,128}$")
            || epoch < 1 || peer is not ("HOST" or "NATIVE"))
            throw new InvalidDataException("Invalid bridge peer binding.");
        _key = key.ToArray(); _sessionId = sessionId; _epoch = epoch; _peer = peer;
    }

    private (byte[] Raw, string MessageId) Encode(string type, JsonElement body, long deadline, string? reply)
    {
        var messageId = Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant();
        var record = JsonSerializer.SerializeToElement(new {
            schema = "fleet.tutor.bridge.v1", protocol_version = _protocolVersion,
            session_id = _sessionId, bridge_epoch = _epoch, sequence = checked(_sent + 1),
            message_id = messageId, reply_to = reply, deadline_monotonic_ms = deadline,
            cancellation_generation = _cancellationGeneration, message_type = type, body
        });
        var raw = BridgeCodec.Encode(_key, record);
        _sent += 1;
        return (raw, messageId);
    }

    public byte[] Start(long deadlineMs)
    {
        lock (_gate)
        {
            if (_peer != "HOST" || _phase != "NEW") throw new InvalidDataException("Unexpected HELLO start.");
            var (raw, id) = Encode("HELLO", JsonSerializer.SerializeToElement(new { peer = _peer, challenge = _challenge }), deadlineMs, null);
            _handshakeReply = id; _phase = "WAIT_NATIVE_ACK"; return raw;
        }
    }

    public byte[] Acknowledge(long deadlineMs)
    {
        lock (_gate)
        {
            if (_phase is not ("SEND_NATIVE_ACK" or "SEND_HOST_ACK")) throw new InvalidDataException("No challenge to acknowledge.");
            var (raw, id) = Encode("HELLO_ACK", JsonSerializer.SerializeToElement(new {
                peer = _peer, challenge = _challenge, echo_challenge = _remoteChallenge
            }), deadlineMs, _handshakeReply);
            if (_peer == "NATIVE") { _phase = "WAIT_HOST_ACK"; _handshakeReply = id; }
            else _phase = "READY";
            return raw;
        }
    }

    public byte[] Send(string type, JsonElement body, long deadlineMs, string? replyTo)
    {
        lock (_gate)
        {
            if (_phase != "READY" || type is "HELLO" or "HELLO_ACK") throw new InvalidDataException("Mutual handshake required.");
            Operation(type, _peer, replyTo, _pendingReceived, deadlineMs);
            if (Replies.ContainsKey(type) && _pendingSent.Count >= 128) throw new InvalidDataException("Pending request limit.");
            var (raw, id) = Encode(type, body, deadlineMs, replyTo);
            if (Replies.ContainsKey(type)) _pendingSent.Add(id, (type, deadlineMs));
            if (replyTo is not null) _pendingReceived.Remove(replyTo);
            return raw;
        }
    }

    private static void Operation(string type, string sender, string? reply, Dictionary<string, (string Kind, long Deadline)> pending, long deadline)
    {
        var permitted = sender == "HOST"
            ? type is "CAPTURE_AUTHORIZATION" or "FRAME_ACCEPTED" or "ANSWER" or "PRESENTATION_RETIRED" or "PAUSE" or "STOP" or "UNAVAILABLE" or "REFUSAL" or "PRACTICE_RESULT"
            : type is "SELECT_SOURCE" or "FRAME" or "OBSERVATION" or "ASK" or "QUESTION" or "PAUSE" or "STOP" or "UNAVAILABLE" or "REFUSAL" or "PRACTICE_REQUEST";
        if (!permitted) throw new InvalidDataException("Message outside sender role.");
        if (type is "ANSWER" or "CAPTURE_AUTHORIZATION" or "FRAME_ACCEPTED" or "PRACTICE_RESULT" || reply is not null)
        {
            if (reply is null || !pending.TryGetValue(reply, out var request)
                || (type != Replies[request.Kind] && type is not ("REFUSAL" or "UNAVAILABLE")))
                throw new InvalidDataException("Reply does not match pending request.");
            if (deadline > request.Deadline) throw new InvalidDataException("Reply exceeds original request lifetime.");
        }
    }

    public void AdvanceGeneration(long generation)
    {
        lock (_gate)
        {
            if (_phase == "CLOSED" || generation < _cancellationGeneration) throw new InvalidDataException("Cancellation generation cannot regress.");
            if (generation != _cancellationGeneration)
            { _cancellationGeneration = generation; _pendingSent.Clear(); _pendingReceived.Clear(); }
        }
    }

    public void ExpirePending(long nowMs)
    {
        lock (_gate)
        {
            if (nowMs < 0) throw new InvalidDataException("Invalid bridge clock.");
            foreach (var pending in new[] { _pendingSent, _pendingReceived })
                foreach (var entry in pending.Where(pair => pair.Value.Deadline <= nowMs).ToArray())
                    pending.Remove(entry.Key);
        }
    }

    public JsonDocument Receive(byte[] raw, long nowMs)
    {
        lock (_gate)
        {
            if (_phase == "CLOSED") throw new InvalidDataException("Bridge peer is closed.");
            if (nowMs < 0 || raw.Length > BridgeCodec.MaxMessageBytes) throw new InvalidDataException("Invalid bridge clock or length.");
            ExpirePending(nowMs);
            long wireGeneration;
            try
            {
                using var untrusted = JsonDocument.Parse(raw, new JsonDocumentOptions { MaxDepth = 32 });
                wireGeneration = untrusted.RootElement.GetProperty("cancellation_generation").GetInt64();
            }
            catch (Exception error) when (error is JsonException or InvalidOperationException or KeyNotFoundException or FormatException)
            { throw new InvalidDataException("Invalid bridge generation.", error); }
            var document = BridgeCodec.Decode(_key, raw, _sessionId, _epoch, checked(_received + 1), wireGeneration, 0);
            try
            {
                var root = document.RootElement;
                if (root.GetProperty("protocol_version").GetString()!=_protocolVersion) throw new InvalidDataException("Bridge version differs from launch selection.");
                var type = root.GetProperty("message_type").GetString();
                var body = root.GetProperty("body");
                var phase = _phase;
                if (wireGeneration > _cancellationGeneration) throw new InvalidDataException("Future cancellation generation.");
                if (wireGeneration < _cancellationGeneration || root.GetProperty("deadline_monotonic_ms").GetInt64() <= nowMs)
                {
                    var remote = _peer == "HOST" ? "NATIVE" : "HOST";
                    var permitted = remote == "HOST"
                        ? type is "CAPTURE_AUTHORIZATION" or "FRAME_ACCEPTED" or "ANSWER" or "PRESENTATION_RETIRED" or "PAUSE" or "STOP" or "UNAVAILABLE" or "REFUSAL" or "PRACTICE_RESULT"
                        : type is "SELECT_SOURCE" or "FRAME" or "OBSERVATION" or "ASK" or "QUESTION" or "PAUSE" or "STOP" or "UNAVAILABLE" or "REFUSAL" or "PRACTICE_REQUEST";
                    if (phase == "READY" && permitted)
                    {
                        _received += 1;
                        _history.Enqueue((_received, Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant()));
                        while (_history.Count > 128) _history.Dequeue();
                        throw new StaleBridgeMessageException();
                    }
                    throw new InvalidDataException("Expired or stale message outside established peer traffic.");
                }
                if (type == "HELLO")
                {
                    if (_peer != "NATIVE" || phase != "NEW" || body.GetProperty("peer").GetString() != "HOST"
                        || root.GetProperty("reply_to").ValueKind != JsonValueKind.Null)
                        throw new InvalidDataException("Unexpected or reflected HELLO.");
                    phase = "SEND_NATIVE_ACK";
                }
                else if (type == "HELLO_ACK")
                {
                    var expectedPhase = _peer == "HOST" ? "WAIT_NATIVE_ACK" : "WAIT_HOST_ACK";
                    var remotePeer = _peer == "HOST" ? "NATIVE" : "HOST";
                    if (phase != expectedPhase || body.GetProperty("peer").GetString() != remotePeer
                        || body.GetProperty("echo_challenge").GetString() != _challenge
                        || root.GetProperty("reply_to").GetString() != _handshakeReply)
                        throw new InvalidDataException("Handshake challenge or correlation mismatch.");
                    if (_peer == "NATIVE" && body.GetProperty("challenge").GetString() != _remoteChallenge)
                        throw new InvalidDataException("Host challenge changed.");
                    phase = _peer == "HOST" ? "SEND_HOST_ACK" : "READY";
                }
                else if (phase != "READY") throw new InvalidDataException("Operation before mutual proof.");
                else
                {
                    Operation(type!, _peer == "HOST" ? "NATIVE" : "HOST", root.GetProperty("reply_to").GetString(), _pendingSent, root.GetProperty("deadline_monotonic_ms").GetInt64());
                    if (Replies.ContainsKey(type!) && _pendingReceived.Count >= 128) throw new InvalidDataException("Pending request limit.");
                }
                if (type is "HELLO" or "HELLO_ACK")
                {
                    _remoteChallenge = body.GetProperty("challenge").GetString();
                    _handshakeReply = root.GetProperty("message_id").GetString();
                }
                _phase = phase; _received += 1;
                if (Replies.ContainsKey(type!)) _pendingReceived.Add(root.GetProperty("message_id").GetString()!, (type!, root.GetProperty("deadline_monotonic_ms").GetInt64()));
                if (type is not ("HELLO" or "HELLO_ACK") && root.GetProperty("reply_to").GetString() is string reply)
                    _pendingSent.Remove(reply);
                _history.Enqueue((_received, Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant()));
                while (_history.Count > 128) _history.Dequeue();
                return document;
            }
            catch { document.Dispose(); throw; }
        }
    }

    public void Dispose()
    {
        lock (_gate) { _phase = "CLOSED"; CryptographicOperations.ZeroMemory(_key); _history.Clear(); _pendingSent.Clear(); _pendingReceived.Clear(); }
    }
}
