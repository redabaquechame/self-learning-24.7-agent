using System.Buffers.Binary;
using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Channels;

namespace ScreenTutor;

public sealed class SourceApprovalPendingException(string detail) : Exception(detail);

public sealed record TutorAnswer(JsonElement Instruction, JsonElement? Presentation);

/// <summary>Inherited per-launch bootstrap and authenticated native-owned pipe.</summary>
public sealed class NativeHostClient : IAsyncDisposable
{
    private readonly OwnerBridge _bridge;
    private readonly string _session;
    private readonly string _protocolVersion;
    private readonly byte[] _key;
    private readonly object _gate = new();
    private readonly Dictionary<string, TaskCompletionSource<JsonDocument>> _replyWaiters = new();
    private readonly SemaphoreSlim _requestGate = new(1, 1);
    private readonly CancellationTokenSource _lifetimeStop = new();
    private FrameTransfer? _publisher;
    private CaptureSession? _capture;
    private SelectedSourceReceipt? _selected;
    private JsonElement? _authorization;
    private long _captureGeneration;
    private Task _sourceStopTail = Task.CompletedTask;
    private bool _stopped;
    private int _disposed;
    private readonly Channel<JsonDocument> _inbox = Channel.CreateBounded<JsonDocument>(4);
    private Task? _receiver;
    public event Action<string, CaptureSession?>? SourceControl;
    public event Action<JsonElement>? PresentationRetired;
    private readonly Queue<JsonElement> _retiredPresentations = new();
    internal bool IsPresentationCurrent(JsonElement binding)
    {
        lock(_gate) return !_retiredPresentations.Any(old => JsonElement.DeepEquals(old,binding));
    }
    private NativeHostClient(OwnerBridge bridge, string session, byte[] key, string protocolVersion="1.1")
    { _bridge = bridge; _session = session; _key = key.ToArray(); _protocolVersion=protocolVersion; }
    public bool Ready => _bridge.Ready;
    public bool PracticeSupported => _protocolVersion=="1.2";

    public static async Task<NativeHostClient> OpenAsync(Stream bootstrap, CancellationToken stop)
    {
        using var bounded = CancellationTokenSource.CreateLinkedTokenSource(stop);
        bounded.CancelAfter(TimeSpan.FromSeconds(10));
        byte[]? payload = null; byte[]? key = null; OwnerBridge? bridge = null;
        try
        {
            var header = new byte[4]; await bootstrap.ReadExactlyAsync(header, bounded.Token).ConfigureAwait(false);
            var length = BinaryPrimitives.ReadInt32BigEndian(header);
            if (length <= 0 || length > 4096) throw new InvalidDataException("Bootstrap length outside bounds.");
            payload = new byte[length]; await bootstrap.ReadExactlyAsync(payload, bounded.Token).ConfigureAwait(false);
            using var record = JsonDocument.Parse(payload, new JsonDocumentOptions { MaxDepth = 8 });
            var root = record.RootElement;
            BridgeCodec.Closed(root, ["schema", "protocol_version", "session_id", "bridge_epoch", "pipe_name", "host_process_id", "key_base64", "deadline_monotonic_ms"]);
            var protocolVersion=root.GetProperty("protocol_version").GetString();
            if (root.GetProperty("schema").GetString() != "fleet.tutor.bootstrap.v1" || protocolVersion is not ("1.1" or "1.2")) throw new InvalidDataException("Unsupported bootstrap version.");
            BridgeCodec.Text(root.GetProperty("session_id"), 128, true);
            var session = root.GetProperty("session_id").GetString()!;
            var epoch = BridgeCodec.Integer(root.GetProperty("bridge_epoch"), 1);
            var pid = BridgeCodec.Integer(root.GetProperty("host_process_id"), 1);
            if (pid > int.MaxValue) throw new InvalidDataException("Invalid host process binding.");
            var name = root.GetProperty("pipe_name").GetString() ?? "";
            if (!Regex.IsMatch(name, "^fleet-screen-tutor-[0-9a-f]{32}$")) throw new InvalidDataException("Invalid launch-owned pipe name.");
            var deadline = BridgeCodec.Integer(root.GetProperty("deadline_monotonic_ms"), 1);
            var remaining = deadline - Environment.TickCount64;
            if (remaining <= 0 || remaining > 10000) throw new InvalidDataException("Expired or excessive bootstrap lifetime.");
            key = Convert.FromBase64String(root.GetProperty("key_base64").GetString() ?? "");
            if (key.Length != 32) throw new InvalidDataException("Invalid launch key.");
            bounded.CancelAfter(TimeSpan.FromMilliseconds(remaining));
            bridge = new OwnerBridge(name, key, session, epoch, expectedClientProcessId: (uint)pid, protocolVersion: protocolVersion);
            await bridge.AcceptAsync(bounded.Token).ConfigureAwait(false);
            using var hello = await bridge.ReadAuthenticatedAsync(bounded.Token).ConfigureAwait(false);
            if (hello.RootElement.GetProperty("message_type").GetString() != "HELLO") throw new InvalidDataException("Expected initial host proof.");
            await bridge.AcknowledgeAsync(deadline, bounded.Token).ConfigureAwait(false);
            using var final = await bridge.ReadAuthenticatedAsync(bounded.Token).ConfigureAwait(false);
            if (!bridge.Ready) throw new InvalidDataException("Mutual host proof incomplete.");
            return new NativeHostClient(bridge, session, key, protocolVersion);
        }
        catch
        {
            if (bridge is not null) await bridge.DisposeAsync().ConfigureAwait(false);
            throw new InvalidDataException("Native host bootstrap unavailable.");
        }
        finally
        {
            if (key is not null) CryptographicOperations.ZeroMemory(key);
            if (payload is not null) CryptographicOperations.ZeroMemory(payload);
        }
    }

    public void StartReceiving()
    {
        lock (_gate)
        {
            if (_stopped || !Ready) throw new InvalidDataException("Host connection unavailable.");
            if (_receiver is not null) return;
            _receiver = ReceiveLoopAsync();
        }
    }

    private async Task ReceiveLoopAsync()
    {
        try
        {
            while (!_lifetimeStop.IsCancellationRequested)
            {
                JsonDocument message;
                try { message = await _bridge.ReadAuthenticatedAsync(_lifetimeStop.Token).ConfigureAwait(false); }
                catch (StaleBridgeMessageException) { continue; }
                var root = message.RootElement; var kind = root.GetProperty("message_type").GetString()!;
                if (root.GetProperty("reply_to").ValueKind == JsonValueKind.Null)
                {
                    if (kind == "PRESENTATION_RETIRED")
                    {
                        var binding = root.GetProperty("body").GetProperty("binding").Clone();
                        lock(_gate)
                        {
                            _retiredPresentations.Enqueue(binding);
                            while(_retiredPresentations.Count>128) _retiredPresentations.Dequeue();
                        }
                        PresentationRetired?.Invoke(binding);
                    }
                    if (kind is "STOP" or "PAUSE" or "UNAVAILABLE")
                    {
                        CaptureSession? capture;
                        lock (_gate) capture = _capture;
                        StopCapture();
                        SourceControl?.Invoke(kind, capture);
                    }
                    message.Dispose();
                    continue;
                }
                bool delivered;
                lock (_gate)
                {
                    var replyTo = root.GetProperty("reply_to").GetString()!;
                    delivered = _replyWaiters.TryGetValue(replyTo, out var waiter) && waiter.TrySetResult(message);
                }
                if (!delivered) message.Dispose(); // Canceled requests never occupy or block the receive pump.
            }
        }
        catch (Exception)
        {
            CaptureSession? capture;
            lock (_gate) capture = _capture;
            Stop();
            SourceControl?.Invoke("DISCONNECTED", capture);
        }
        finally { _inbox.Writer.TryComplete(); }
    }

    public Task<JsonDocument> ReadAsync(CancellationToken stop)
    {
        lock (_gate)
            return _receiver is null ? _bridge.ReadAuthenticatedAsync(stop) : _inbox.Reader.ReadAsync(stop).AsTask();
    }
    public Task SendAsync(string kind, JsonElement body, long deadline, string? reply, CancellationToken stop)
        => _bridge.WriteAuthenticatedAsync(kind, body, deadline, reply, stop);

    private async Task<JsonDocument> RequestAsync(string kind, JsonElement body, long deadline, CancellationToken stop)
    {
        var waiter = new TaskCompletionSource<JsonDocument>(TaskCreationOptions.RunContinuationsAsynchronously);
        string? messageId = null;
        bool receiving = false, delivered = false;
        try
        {
            await _bridge.WriteAuthenticatedAsync(kind, body, deadline, null, stop, id =>
            {
                lock (_gate)
                {
                    if (_stopped || !Ready) throw new InvalidDataException("Host connection unavailable.");
                    messageId = id; receiving = _receiver is not null;
                    if (receiving)
                    {
                        if (_replyWaiters.Count >= 128) throw new InvalidDataException("Native reply waiter limit.");
                        _replyWaiters.Add(id, waiter);
                    }
                }
            }).ConfigureAwait(false);
            if (receiving)
            {
                var response = await waiter.Task.WaitAsync(stop).ConfigureAwait(false);
                stop.ThrowIfCancellationRequested(); delivered = true;
                return response;
            }
            while (true)
            {
                JsonDocument response;
                try { response = await ReadAsync(stop).ConfigureAwait(false); }
                catch (StaleBridgeMessageException) { continue; }
                if (response.RootElement.GetProperty("reply_to").GetString() == messageId) return response;
                response.Dispose();
            }
        }
        finally
        {
            lock (_gate)
            {
                if (messageId is not null) _replyWaiters.Remove(messageId);
                if (!delivered && waiter.Task.IsCompletedSuccessfully) waiter.Task.Result.Dispose();
            }
        }
    }

    public async Task<JsonElement> PracticeAsync(string operation, byte[]? artifact, CancellationToken stop)
    {
        if (!PracticeSupported || operation is not ("STATUS" or "START" or "UPLOAD" or "SUBMIT" or "CANCEL"))
            throw new InvalidDataException("Human practice is unavailable.");
        if (operation=="UPLOAD" ? artifact is null || artifact.Length is <1 or >262144 : artifact is not null)
            throw new InvalidDataException("Practice artifact is outside bounds.");
        // Snapshot exact selected bytes before awaiting any transport gate.
        var payload=operation=="UPLOAD" ? JsonSerializer.SerializeToElement(new { artifact_base64=Convert.ToBase64String(artifact!) }) : JsonSerializer.SerializeToElement(new { });
        using var bounded=CancellationTokenSource.CreateLinkedTokenSource(stop,_lifetimeStop.Token);
        bounded.CancelAfter(TimeSpan.FromSeconds(15));
        await _requestGate.WaitAsync(bounded.Token).ConfigureAwait(false);
        try
        {
            lock(_gate) if(_stopped || !Ready)throw new InvalidDataException("Practice connection unavailable.");
            using var reply=await RequestAsync("PRACTICE_REQUEST",JsonSerializer.SerializeToElement(new { schema="fleet.tutor.practice-request.v1",operation,payload }),
                Environment.TickCount64+15000,bounded.Token).ConfigureAwait(false);
            bounded.Token.ThrowIfCancellationRequested();
            lock(_gate) if(_stopped || !Ready)throw new InvalidDataException("Practice stopped before result.");
            var root=reply.RootElement;
            if(root.GetProperty("message_type").GetString()!="PRACTICE_RESULT")
                throw new InvalidDataException(root.GetProperty("body").TryGetProperty("detail",out var detail)?detail.GetString():"Practice request refused.");
            return root.GetProperty("body").Clone();
        }
        finally{_requestGate.Release();}
    }

    public async Task<JsonElement> RequestCaptureAuthorizationAsync(SelectedSourceReceipt source, CancellationToken stop)
    {
        ArgumentNullException.ThrowIfNull(source);
        using var bounded = CancellationTokenSource.CreateLinkedTokenSource(stop, _lifetimeStop.Token);
        bounded.CancelAfter(TimeSpan.FromSeconds(10));
        Task pendingStop;
        lock (_gate) pendingStop = _sourceStopTail;
        await pendingStop.WaitAsync(bounded.Token).ConfigureAwait(false);
        await _requestGate.WaitAsync(bounded.Token).ConfigureAwait(false);
        try
        {
            if (!Ready) throw new InvalidDataException("Native host unavailable.");
            var receipt = JsonSerializer.SerializeToElement(new { source_id = source.SourceId, display_name = source.DisplayName,
                source_kind = source.SourceKind, source_revision = source.SourceRevision, native_handle_digest = source.NativeHandleDigest,
                width = source.Width, height = source.Height, capture_epoch = source.CaptureEpoch });
            using var reply = await RequestAsync("SELECT_SOURCE", receipt, Environment.TickCount64 + 10000, bounded.Token).ConfigureAwait(false);
            var root = reply.RootElement;
            if (root.GetProperty("message_type").GetString() != "CAPTURE_AUTHORIZATION")
            {
                var refused=root.GetProperty("body");
                bounded.Token.ThrowIfCancellationRequested();
                if(root.GetProperty("message_type").GetString()=="REFUSAL"
                    && refused.GetProperty("reason_code").GetString()=="SOURCE_APPROVAL_PENDING")
                    throw new SourceApprovalPendingException(refused.GetProperty("detail").GetString()!);
                throw new InvalidDataException(refused.TryGetProperty("detail",out var detail)
                    ? detail.GetString() : "Current host refused source authorization.");
            }
            var authorization = root.GetProperty("body");
            var now = Environment.TickCount64;
            if (authorization.GetProperty("source_id").GetString() != source.SourceId
                || authorization.GetProperty("source_revision").GetString() != source.SourceRevision
                || authorization.GetProperty("capture_epoch").GetInt64() != source.CaptureEpoch
                || authorization.GetProperty("now_monotonic_ms").GetInt64() > now
                || authorization.GetProperty("expires_at_monotonic_ms").GetInt64() <= now)
                throw new InvalidDataException("Current host authorization is stale or foreign.");
            bounded.Token.ThrowIfCancellationRequested();
            return authorization.Clone();
        }
        finally { _requestGate.Release(); }
    }

    public FrameTransfer CreateFrameTransfer()
    {
        FrameTransfer? previous;
        FrameTransfer next;
        lock (_gate)
        {
            if (_stopped || !Ready) throw new InvalidDataException("Native frame connection unavailable.");
            previous = _publisher; next = _publisher = new FrameTransfer(_session, _key);
        }
        previous?.Dispose();
        return next;
    }

    public async Task<JsonElement> AuthorizeCaptureAsync(CaptureSession capture, SelectedSourceReceipt source, CancellationToken stop)
    {
        ArgumentNullException.ThrowIfNull(capture);
        ArgumentNullException.ThrowIfNull(source);
        if (capture.State != CaptureLifecycle.Ready || capture.SelectedSource != source)
            throw new InvalidDataException("Native source changed before authorization.");
        FrameTransfer? previous;
        CaptureSession? previousCapture; SelectedSourceReceipt? previousSource;
        long generation;
        lock (_gate)
        {
            if (_stopped || !Ready) throw new InvalidDataException("Native host unavailable.");
            previous = _publisher; _publisher = null; _authorization = null;
            previousCapture = _capture; previousSource = _selected;
            _capture = capture; _selected = source; generation = ++_captureGeneration;
        }
        previous?.Dispose();
        if (previousCapture is not null && previousSource is not null) previousCapture.StopSelectedSource(previousSource);
        EventHandler unavailable = (_, _) => ReleaseCapture(capture, source, generation, stopCapture: false);
        capture.SourceUnavailable += unavailable;
        try
        {
            var authorization = await RequestCaptureAuthorizationAsync(source, stop).ConfigureAwait(false);
            lock (_gate)
            {
                if (_stopped || !Ready || _captureGeneration != generation || _capture != capture
                    || capture.State != CaptureLifecycle.Ready || capture.SelectedSource != source)
                    throw new InvalidDataException("Native selection stopped before capture authorization.");
                _authorization = authorization.Clone();
                _publisher = new FrameTransfer(_session, _key);
            }
            // IO completed before touching capture's lifecycle gate. Use the
            // remaining bridge lifetime, not the original issue-time duration.
            capture.StartAuthorizedCapture(source.SourceId, source.SourceRevision, source.CaptureEpoch,
                Environment.TickCount64, authorization.GetProperty("expires_at_monotonic_ms").GetInt64());
            lock (_gate)
            {
                if (_stopped || _captureGeneration != generation || capture.SelectedSource != source)
                    throw new InvalidDataException("Native source stopped during capture startup.");
            }
            return authorization;
        }
        catch (SourceApprovalPendingException)
        {
            capture.SourceUnavailable -= unavailable;
            ReleaseCapture(capture, source, generation, stopCapture: false);
            throw;
        }
        catch
        {
            capture.SourceUnavailable -= unavailable;
            ReleaseCapture(capture, source, generation, stopCapture: true);
            throw;
        }
    }

    public JsonElement PublishFrame(CapturedFrame frame)
    {
        FrameTransfer publisher; JsonElement authorization; CaptureSession capture;
        SelectedSourceReceipt source; long generation;
        lock (_gate)
        {
            if (_stopped || !Ready || _publisher is null || _authorization is null || _capture is null || _selected is null)
                throw new InvalidDataException("Native frame source authorization unavailable.");
            publisher = _publisher; authorization = _authorization.Value;
            capture = _capture; source = _selected; generation = _captureGeneration;
        }
        if (capture.State != CaptureLifecycle.Ready || capture.SelectedSource != source)
            throw new InvalidDataException("Native frame source changed.");
        var reference = publisher.Publish(frame, authorization);
        lock (_gate)
        {
            if (_stopped || generation != _captureGeneration || _publisher != publisher
                || capture.State != CaptureLifecycle.Ready || capture.SelectedSource != source)
                throw new InvalidDataException("Native frame source stopped during publication.");
        }
        return reference;
    }

    public async Task<JsonElement> SendFrameAsync(CapturedFrame frame, CancellationToken stop)
    {
        ArgumentNullException.ThrowIfNull(frame);
        using var bounded = CancellationTokenSource.CreateLinkedTokenSource(stop, _lifetimeStop.Token);
        bounded.CancelAfter(TimeSpan.FromSeconds(2));
        Task pendingStop;
        CaptureSession capture; SelectedSourceReceipt source; long generation; JsonElement reference;
        FrameTransfer? publisher = null; JsonElement? published = null;
        try
        {
        try
        {
            lock (_gate)
            {
                if (_stopped || !Ready || _capture is null || _selected is null || _authorization is null || _publisher is null)
                    throw new InvalidDataException("Native frame source unavailable.");
                capture = _capture; source = _selected; generation = _captureGeneration;
                pendingStop = _sourceStopTail; publisher = _publisher;
            }
            reference = PublishFrame(frame); published = reference;
        }
        finally { frame.Dispose(); } // No raw pixels survive any awaited gate or reply.
        await pendingStop.WaitAsync(bounded.Token).ConfigureAwait(false);
        await _requestGate.WaitAsync(bounded.Token).ConfigureAwait(false);
        try
        {
            lock (_gate)
            {
                if (_stopped || !Ready || generation != _captureGeneration || _capture != capture || _selected != source
                    || _authorization is null || capture.State != CaptureLifecycle.Ready || capture.SelectedSource != source)
                    throw new InvalidDataException("Native frame source changed while queued.");
            }
            using var reply = await RequestAsync("FRAME", JsonSerializer.SerializeToElement(new { frame_reference = reference }),
                Environment.TickCount64 + 2000, bounded.Token).ConfigureAwait(false);
            var root = reply.RootElement;
            if (root.GetProperty("message_type").GetString() != "FRAME_ACCEPTED")
                throw new InvalidDataException("Current host did not admit this frame.");
            var observation = root.GetProperty("body").GetProperty("observation");
            lock (_gate)
            {
                if (_stopped || !Ready || generation != _captureGeneration || _capture != capture || _selected != source
                    || capture.State != CaptureLifecycle.Ready || capture.SelectedSource != source
                    || observation.GetProperty("source_id").GetString() != source.SourceId
                    || observation.GetProperty("source_revision").GetString() != source.SourceRevision
                    || observation.GetProperty("capture_epoch").GetInt64() != source.CaptureEpoch
                    || observation.GetProperty("session_id").GetString() != _authorization?.GetProperty("session_id").GetString()
                    || observation.GetProperty("consent_revision").GetString() != _authorization?.GetProperty("consent_revision").GetString())
                    throw new InvalidDataException("Native source changed before observation admission.");
            }
            return observation.Clone();
        }
        finally { _requestGate.Release(); }
        }
        finally
        {
            if (publisher is not null && published is { } completed)
                publisher.Release(completed.GetProperty("transfer_id").GetString()!);
        }
    }

    public async Task<JsonElement> SendQuestionAsync(JsonElement observation, string requestId, string question, string learningIntent, string locale, CancellationToken stop)
        => (await SendTeachingQuestionAsync(observation,requestId,question,learningIntent,locale,stop).ConfigureAwait(false)).Instruction;

    public async Task<TutorAnswer> SendTeachingQuestionAsync(JsonElement observation, string requestId, string question, string learningIntent, string locale, CancellationToken stop)
    {
        using var bounded = CancellationTokenSource.CreateLinkedTokenSource(stop, _lifetimeStop.Token);
        bounded.CancelAfter(TimeSpan.FromSeconds(15));
        await _requestGate.WaitAsync(bounded.Token).ConfigureAwait(false);
        try
        {
            CaptureSession capture; SelectedSourceReceipt source; long generation;
            lock (_gate)
            {
                if (_stopped || !Ready || _capture is null || _selected is null || _authorization is null)
                    throw new InvalidDataException("Selected source is unavailable.");
                capture = _capture; source = _selected; generation = _captureGeneration;
                if (observation.GetProperty("source_id").GetString() != source.SourceId
                    || observation.GetProperty("source_revision").GetString() != source.SourceRevision
                    || observation.GetProperty("capture_epoch").GetInt64() != source.CaptureEpoch
                    || observation.GetProperty("session_id").GetString() != _authorization.Value.GetProperty("session_id").GetString())
                    throw new InvalidDataException("Observation no longer matches the selected source.");
            }
            using var reply = await RequestAsync("QUESTION", JsonSerializer.SerializeToElement(new { request_id = requestId,
                observation_id = observation.GetProperty("observation_id").GetString(), question, learning_intent = learningIntent, locale }),
                Environment.TickCount64 + 15000, bounded.Token).ConfigureAwait(false);
            var root = reply.RootElement;
            if (root.GetProperty("message_type").GetString() != "ANSWER")
                throw new InvalidDataException(root.GetProperty("body").TryGetProperty("detail", out var detail)
                    ? detail.GetString() : "The answer service is unavailable.");
            var instruction = root.GetProperty("body").GetProperty("instruction");
            lock (_gate)
            {
                if (_stopped || !Ready || generation != _captureGeneration || _capture != capture || _selected != source
                    || capture.State != CaptureLifecycle.Ready || capture.SelectedSource != source
                    || instruction.GetProperty("request_id").GetString() != requestId)
                    throw new InvalidDataException("Source changed before the answer arrived.");
            }
            JsonElement? presentation = null;
            if (root.GetProperty("body").TryGetProperty("presentation",out var teaching))
            {
                var binding=teaching.GetProperty("binding");
                foreach (var name in new[]{"session_id","user_id","tenant_id","project_id","observation_id","source_id","source_revision","geometry_revision","content_sha256","consent_revision"})
                    if (binding.GetProperty(name).GetString()!=observation.GetProperty(name).GetString())
                        throw new InvalidDataException("Teaching scene does not match the selected source evidence.");
                lock (_gate)
                {
                    if (_authorization is null || generation!=_captureGeneration
                        || binding.GetProperty("capture_epoch").GetInt64()!=source.CaptureEpoch
                        || binding.GetProperty("cancellation_generation").GetInt64()!=_authorization.Value.GetProperty("cancellation_generation").GetInt64()
                        || teaching.GetProperty("expires_at_monotonic_ms").GetInt64()<=Environment.TickCount64
                        || teaching.GetProperty("expires_at_monotonic_ms").GetInt64()>observation.GetProperty("expires_at_monotonic_ms").GetInt64()
                        || teaching.GetProperty("expires_at_monotonic_ms").GetInt64()>_authorization.Value.GetProperty("expires_at_monotonic_ms").GetInt64())
                        throw new InvalidDataException("Teaching scene permission changed or expired.");
                }
                if (!IsPresentationCurrent(teaching.GetProperty("binding")))
                    throw new InvalidDataException("Teaching authorization changed before display.");
                presentation=teaching.Clone();
            }
            return new TutorAnswer(instruction.Clone(),presentation);
        }
        finally { _requestGate.Release(); }
    }

    private void ReleaseCapture(CaptureSession capture, SelectedSourceReceipt source, long generation, bool stopCapture)
    {
        FrameTransfer? publisher;
        lock (_gate)
        {
            if (_capture != capture || _selected != source || _captureGeneration != generation) return;
            publisher = _publisher; _publisher = null; _authorization = null; _capture = null; _selected = null;
            _captureGeneration++;
        }
        publisher?.Dispose();
        if (stopCapture) capture.StopSelectedSource(source);
    }

    public void StopCapture()
    {
        CaptureSession? capture; SelectedSourceReceipt? source; long generation;
        lock (_gate) { capture = _capture; source = _selected; generation = _captureGeneration; }
        if (capture is not null && source is not null) ReleaseCapture(capture, source, generation, stopCapture: true);
        else StopFrameTransfer();
    }

    public void PauseCapture()
    {
        CaptureSession? capture; SelectedSourceReceipt? source; long generation;
        lock (_gate) { capture = _capture; source = _selected; generation = _captureGeneration; }
        if (capture is not null && source is not null)
        {
            capture.Pause();
            ReleaseCapture(capture, source, generation, stopCapture: false);
        }
        else StopFrameTransfer();
    }

    public Task NotifySourcePausedAsync()
    {
        lock (_gate)
        {
            if (_stopped || !Ready) return Task.CompletedTask;
            return _sourceStopTail = NotifySourceStoppedCoreAsync(_sourceStopTail, "PAUSE");
        }
    }

    public Task NotifySourceStoppedAsync()
    {
        lock (_gate)
        {
            if (_stopped || !Ready) return Task.CompletedTask;
            return _sourceStopTail = NotifySourceStoppedCoreAsync(_sourceStopTail);
        }
    }

    private async Task NotifySourceStoppedCoreAsync(Task prior, string kind = "STOP")
    {
        using var bounded = CancellationTokenSource.CreateLinkedTokenSource(_lifetimeStop.Token);
        bounded.CancelAfter(TimeSpan.FromSeconds(10));
        await prior.WaitAsync(bounded.Token).ConfigureAwait(false);
        // Stop is a one-way control, not another request/reply. The bridge
        // serializes writes; an outstanding reply must not delay notification.
        if (!Ready) throw new InvalidDataException("Native source Stop connection unavailable.");
        await SendAsync(kind, JsonSerializer.SerializeToElement(new { reason_code = kind == "PAUSE" ? "SOURCE_PAUSED" : "SOURCE_STOPPED" }),
            Environment.TickCount64 + 2000, null, bounded.Token).ConfigureAwait(false);
    }

    public void StopFrameTransfer()
    {
        FrameTransfer? publisher;
        lock (_gate) { publisher = _publisher; _publisher = null; }
        publisher?.Dispose();
    }

    public void Stop()
    {
        lock (_gate)
        {
            if (_stopped) return;
            _stopped = true;
            CryptographicOperations.ZeroMemory(_key);
            _lifetimeStop.Cancel();
        }
        _bridge.Stop(); StopCapture();
        while (_inbox.Reader.TryRead(out var pending)) pending.Dispose();
    }

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0) return;
        Stop();
        await _bridge.DisposeAsync().ConfigureAwait(false);
    }
}
