using System.Buffers.Binary;
using System.IO;
using System.IO.Pipes;
using System.Text.Json;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace ScreenTutor;

public sealed class OwnerBridge : IAsyncDisposable
{
    public const int MaxMessageBytes = BridgeCodec.MaxMessageBytes;
    private readonly string _pipeName;
    private readonly BridgePeer _peer;
    private readonly Func<long> _clock;
    private readonly uint _expectedClientPid;
    private readonly CancellationTokenSource _stop = new();
    private readonly SemaphoreSlim _writeGate = new(1, 1);
    private readonly SemaphoreSlim _readGate = new(1, 1);
    private NamedPipeServerStream? _pipe;
    public bool Ready => !_stop.IsCancellationRequested && _peer.Ready;

    public OwnerBridge(string pipeName, byte[] sessionKey, string sessionId, long bridgeEpoch,
        Func<long>? monotonicClock = null, uint expectedClientProcessId = 0, string protocolVersion = "1.1")
    {
        if (string.IsNullOrWhiteSpace(pipeName)) throw new ArgumentException("Pipe name required.", nameof(pipeName));
        _pipeName = pipeName;
        _peer = new BridgePeer(sessionKey, sessionId, bridgeEpoch, "NATIVE", protocolVersion);
        _clock = monotonicClock ?? (() => Environment.TickCount64);
        _expectedClientPid = expectedClientProcessId;
    }

    public async Task AcceptAsync(CancellationToken cancellationToken)
    {
        if (_pipe is not null) throw new InvalidOperationException("Bridge already accepted a peer.");
        var owner = WindowsIdentity.GetCurrent().User ?? throw new InvalidDataException("Native user binding unavailable.");
        var security = new PipeSecurity();
        security.SetAccessRuleProtection(true, false); security.SetOwner(owner);
        security.AddAccessRule(new PipeAccessRule(owner, PipeAccessRights.FullControl, AccessControlType.Allow));
        security.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null), PipeAccessRights.FullControl, AccessControlType.Allow));
        _pipe = NamedPipeServerStreamAcl.Create(_pipeName, PipeDirection.InOut, 1,
            PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.FirstPipeInstance,
            4096, 4096, security, HandleInheritability.None, (PipeAccessRights)0);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, _stop.Token);
        linked.CancelAfter(TimeSpan.FromSeconds(10));
        await _pipe.WaitForConnectionAsync(linked.Token).ConfigureAwait(false);
        if (_expectedClientPid != 0 && (!GetNamedPipeClientProcessId(_pipe.SafePipeHandle, out var pid) || pid != _expectedClientPid))
        { Stop(); throw new InvalidDataException("Native pipe client is a foreign process."); }
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetNamedPipeClientProcessId(SafePipeHandle pipe, out uint processId);

    public async Task<JsonDocument> ReadAuthenticatedAsync(CancellationToken cancellationToken)
    {
        var pipe = _pipe ?? throw new InvalidOperationException("Bridge is not connected.");
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, _stop.Token);
        if (!_peer.Ready) linked.CancelAfter(TimeSpan.FromSeconds(10));
        await _readGate.WaitAsync(linked.Token).ConfigureAwait(false);
        try
        {
            byte[] payload;
            try
            {
                var header = new byte[4];
                var first = new byte[1];
                await ReadExactlyAsync(pipe, first, linked.Token).ConfigureAwait(false);
                // Established peers may be idle. Once framing starts, its
                // remainder stays bounded; caller deadlines/Stop always apply.
                linked.CancelAfter(TimeSpan.FromSeconds(10));
                var rest = new byte[3];
                await ReadExactlyAsync(pipe, rest, linked.Token).ConfigureAwait(false);
                header[0] = first[0]; rest.CopyTo(header, 1);
                var length = BinaryPrimitives.ReadInt32BigEndian(header);
                if (length <= 0 || length > MaxMessageBytes) throw new InvalidDataException("Message length outside bounds.");
                payload = new byte[length];
                await ReadExactlyAsync(pipe, payload, linked.Token).ConfigureAwait(false);
            }
            catch (Exception error) when (error is IOException or OperationCanceledException)
            { Stop(); throw; } // Partial framing cannot be reused after cancellation/EOF.
            linked.Token.ThrowIfCancellationRequested();
            var document = _peer.Receive(payload, _clock());
            try { linked.Token.ThrowIfCancellationRequested(); return document; }
            catch { document.Dispose(); throw; }
        }
        finally { _readGate.Release(); }
    }

    public Task AcknowledgeAsync(long deadlineMs, CancellationToken cancellationToken)
        => WriteFrameAsync(() => _peer.Acknowledge(deadlineMs), deadlineMs, cancellationToken);

    public Task<string> WriteAuthenticatedAsync(string messageType, JsonElement body, long deadlineMs,
        string? replyTo, CancellationToken cancellationToken, Action<string>? prepared = null)
        => WriteFrameAsync(() => _peer.Send(messageType, body, deadlineMs, replyTo), deadlineMs, cancellationToken, prepared);

    private async Task<string> WriteFrameAsync(Func<byte[]> encode, long deadlineMs, CancellationToken cancellationToken, Action<string>? prepared = null)
    {
        var pipe = _pipe ?? throw new InvalidOperationException("Bridge is not connected.");
        var remaining = deadlineMs - _clock();
        if (remaining <= 0) throw new InvalidDataException("Outgoing bridge deadline expired.");
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, _stop.Token);
        linked.CancelAfter(TimeSpan.FromMilliseconds(Math.Min(remaining, 10000)));
        await _writeGate.WaitAsync(linked.Token).ConfigureAwait(false);
        try
        {
            if (deadlineMs <= _clock()) throw new InvalidDataException("Outgoing bridge deadline expired.");
            _peer.ExpirePending(_clock());
            var payload = encode();
            using var outbound = JsonDocument.Parse(payload);
            var messageId = outbound.RootElement.GetProperty("message_id").GetString()!;
            prepared?.Invoke(messageId); // Register the exact waiter before any reply can arrive.
            var header = new byte[4]; BinaryPrimitives.WriteInt32BigEndian(header, payload.Length);
            try
            {
                await pipe.WriteAsync(header, linked.Token).ConfigureAwait(false);
                await pipe.WriteAsync(payload, linked.Token).ConfigureAwait(false);
                await pipe.FlushAsync(linked.Token).ConfigureAwait(false);
            }
            catch { Stop(); throw; } // Partial frame/sequence cannot be retried on this connection.
            return messageId;
        }
        finally { _writeGate.Release(); }
    }

    public void AdvanceGeneration(long generation) => _peer.AdvanceGeneration(generation);
    public void Stop() => _stop.Cancel();

    private static async Task ReadExactlyAsync(Stream stream, byte[] buffer, CancellationToken cancellationToken)
    {
        var offset = 0;
        while (offset < buffer.Length)
        {
            var read = await stream.ReadAsync(buffer.AsMemory(offset), cancellationToken).ConfigureAwait(false);
            if (read == 0) throw new EndOfStreamException();
            offset += read;
        }
    }

    public async ValueTask DisposeAsync()
    {
        _stop.Cancel();
        if (_pipe is not null) await _pipe.DisposeAsync().ConfigureAwait(false);
        _peer.Dispose();
        _stop.Dispose();
    }
}
