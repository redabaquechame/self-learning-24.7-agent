using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using Windows.Graphics;
using Windows.Graphics.Capture;
using Windows.Graphics.DirectX;
using Windows.Graphics.DirectX.Direct3D11;
using Windows.Graphics.Imaging;
using Windows.Storage.Streams;
using WinRT;

namespace ScreenTutor;

public enum CaptureLifecycle { Dormant, Selecting, Ready, Paused, SourceUnavailable, Closed }

public sealed record SelectedSourceReceipt(
    string SourceId, string DisplayName, string SourceKind, string SourceRevision,
    string NativeHandleDigest, uint Width, uint Height, long CaptureEpoch);

public sealed record FrameReceipt(
    string FrameId, string SourceId, string SourceRevision, long CaptureEpoch,
    long CapturedAtMonotonicMilliseconds, uint Width, uint Height,
    string PixelFormat, int SizeBytes, string ContentSha256);

public sealed class CapturedFrame : IDisposable
{
    private byte[]? _pixels;

    internal CapturedFrame(FrameReceipt receipt, byte[] pixels)
    {
        Receipt = receipt;
        _pixels = pixels;
    }

    public FrameReceipt Receipt { get; }
    public ReadOnlyMemory<byte> Pixels => _pixels ?? throw new ObjectDisposedException(nameof(CapturedFrame));

    public void Dispose()
    {
        if (_pixels is not null)
        {
            CryptographicOperations.ZeroMemory(_pixels);
            _pixels = null;
        }
        GC.SuppressFinalize(this);
    }
}

public sealed class CaptureSession : IDisposable
{
    public const int MaxFrames = 3;
    public const int MaxFrameBytes = 32 * 1024 * 1024;
    public const int MaxBufferBytes = 64 * 1024 * 1024;
    public const long MaxAuthorizationLifetimeMilliseconds = 15 * 60 * 1000;
    public const long FrameSilenceTimeoutMilliseconds = 3000;

    private readonly object _gate = new();
    private readonly SemaphoreSlim _copyGate = new(1, 1);
    private readonly Queue<CapturedFrame> _frames = new();
    private readonly Timer _frameWatchdog;
    private GraphicsCaptureItem? _item;
    private IDirect3DDevice? _device;
    private Direct3D11CaptureFramePool? _framePool;
    private GraphicsCaptureSession? _nativeSession;
    private CancellationTokenSource? _captureStop;
    private SizeInt32 _frameSize;
    private volatile CaptureLifecycle _state = CaptureLifecycle.Dormant;
    private long _captureEpoch;
    private int _bufferBytes;
    private long _authorizationExpiresAtMonotonicMilliseconds;
    private long _lastFrameAtMonotonicMilliseconds;

    private readonly Action? _beforeNativeStart;

    public CaptureSession() : this(null) { }

    internal CaptureSession(Action? beforeNativeStart)
    {
        _beforeNativeStart = beforeNativeStart;
        _frameWatchdog = new Timer(CheckFrameHealth, null, 1000, 1000);
    }

    public CaptureLifecycle State => _state;
    public SelectedSourceReceipt? SelectedSource { get; private set; }
    public event EventHandler? SourceUnavailable;
    public event EventHandler<FrameReceipt>? FrameAvailable;
    public event EventHandler<string>? CaptureFailed;

    public void BeginSelection()
    {
        lock (_gate)
        {
            if (_state == CaptureLifecycle.Closed)
                throw new InvalidOperationException("A closed capture session cannot be reopened.");
            if (_state == CaptureLifecycle.Selecting)
                throw new InvalidOperationException("Source picker is already active.");
            InvalidateCaptureLocked(clearItem: true);
            _captureEpoch++;
            _state = CaptureLifecycle.Selecting;
        }
    }

    public Task<SelectedSourceReceipt?> PickSingleSourceAsync(nint ownerWindow)
        => PickSingleSourceAsync(ownerWindow, async owner =>
        {
            var picker = new GraphicsCapturePicker();
            picker.As<IInitializeWithWindow>().Initialize(owner);
            return await picker.PickSingleItemAsync();
        });

    internal async Task<SelectedSourceReceipt?> PickSingleSourceAsync(
        nint ownerWindow, Func<nint, Task<GraphicsCaptureItem?>> picker)
    {
        long selectionEpoch;
        lock (_gate)
        {
            if (_state != CaptureLifecycle.Selecting)
                throw new InvalidOperationException("Source picker is not active.");
            selectionEpoch = _captureEpoch;
        }
        if (!GraphicsCaptureSession.IsSupported())
            return CompleteSelection(null, selectionEpoch);

        var item = await picker(ownerWindow);
        return CompleteSelection(item, selectionEpoch);
    }

    private SelectedSourceReceipt? CompleteSelection(GraphicsCaptureItem? item, long selectionEpoch)
    {
        lock (_gate)
        {
            if (_state != CaptureLifecycle.Selecting || _captureEpoch != selectionEpoch)
                return null;
            if (item is not null) return PrepareSelectedItemLocked(item);
            InvalidateCaptureLocked(clearItem: true);
            SelectedSource = null;
            _captureEpoch++;
            _state = CaptureLifecycle.SourceUnavailable;
        }
        NotifySourceUnavailable();
        return null;
    }

    internal SelectedSourceReceipt PrepareAuthorizedTestSource(GraphicsCaptureItem item)
    {
        ArgumentNullException.ThrowIfNull(item);
        lock (_gate)
        {
            if (_state != CaptureLifecycle.Selecting)
                throw new InvalidOperationException("Synthetic qualification requires an explicit test selection state.");
            return PrepareSelectedItemLocked(item);
        }
    }

    public void StartAuthorizedCapture(
        string sourceId, string sourceRevision, long captureEpoch,
        long nowMonotonicMilliseconds, long expiresAtMonotonicMilliseconds)
    {
        lock (_gate)
        {
            var source = SelectedSource;
            if (_state != CaptureLifecycle.Ready || source is null || _item is null)
                throw new InvalidOperationException("No selected source is ready for authorization.");
            if (_nativeSession is not null)
                throw new InvalidOperationException("Capture is already active for this authorization.");
            if (source.SourceId != sourceId || source.SourceRevision != sourceRevision
                || source.CaptureEpoch != captureEpoch)
                throw new InvalidOperationException("Capture authorization is stale or belongs to another source.");
            var current = MonotonicMilliseconds();
            if (nowMonotonicMilliseconds < 0 || nowMonotonicMilliseconds > current)
                throw new InvalidOperationException("Capture authorization clock is invalid.");
            if (expiresAtMonotonicMilliseconds <= nowMonotonicMilliseconds
                || expiresAtMonotonicMilliseconds <= current)
                throw new InvalidOperationException("Capture authorization is expired.");
            var lifetime = expiresAtMonotonicMilliseconds - nowMonotonicMilliseconds;
            if (lifetime > MaxAuthorizationLifetimeMilliseconds)
                throw new InvalidOperationException("Capture authorization lifetime exceeds the 15-minute boundary.");
            _authorizationExpiresAtMonotonicMilliseconds = expiresAtMonotonicMilliseconds;
            StartCaptureLocked(_item.Size);
        }
    }

    public void Pause()
    {
        lock (_gate)
        {
            if (_state != CaptureLifecycle.Ready || _nativeSession is null) return;
            StopCapturePipelineLocked();
            ClearFramesLocked();
            _state = CaptureLifecycle.Paused;
        }
    }

    public void Resume()
    {
        lock (_gate)
        {
            if (_state != CaptureLifecycle.Paused || _item is null)
                throw new InvalidOperationException("Only a paused selected source can resume.");
            if (MonotonicMilliseconds() >= _authorizationExpiresAtMonotonicMilliseconds)
                throw new InvalidOperationException("Capture authorization expired while paused.");
            StartCaptureLocked(_item.Size);
            _state = CaptureLifecycle.Ready;
        }
    }

    internal SelectedSourceReceipt PrepareResumeAuthorization()
    {
        lock (_gate)
        {
            if (_state != CaptureLifecycle.Paused || _item is null || SelectedSource is null)
                throw new InvalidOperationException("Only a paused selected source can request fresh authorization.");
            InvalidateCaptureLocked(clearItem: false);
            _authorizationExpiresAtMonotonicMilliseconds = 0;
            _captureEpoch++;
            // Retaining the chosen item preserves selection, never its grant.
            // Ready here has no capture pipeline until StartAuthorizedCapture.
            return PrepareSelectedItemLocked(_item);
        }
    }

    public CapturedFrame? TryTakeLatestFrame()
    {
        long? expiredEpoch = null;
        lock (_gate)
        {
            if (_state == CaptureLifecycle.Ready && _nativeSession is not null
                && MonotonicMilliseconds() >= _authorizationExpiresAtMonotonicMilliseconds)
                expiredEpoch = _captureEpoch;
            if (expiredEpoch is null)
            {
            CapturedFrame? latest = null;
            while (_frames.Count > 0)
            {
                var frame = _frames.Dequeue();
                _bufferBytes -= frame.Receipt.SizeBytes;
                latest?.Dispose();
                latest = frame;
            }
            return latest;
            }
        }
        if (MarkSourceUnavailable(expectedEpoch: expiredEpoch))
            NotifyCaptureFailed("Sharing authorization expired. Choose and authorize your source again.");
        return null;
    }

    internal async Task<CapturedFrame> TakeCurrentFrameAsync(CancellationToken stop)
    {
        var buffered = TryTakeLatestFrame();
        if (buffered is not null)
        {
            var age = MonotonicMilliseconds() - buffered.Receipt.CapturedAtMonotonicMilliseconds;
            if (age >= 0 && age < 2000) return buffered;
            buffered.Dispose();
        }
        SelectedSourceReceipt source;
        CancellationToken pipelineStop;
        long expires;
        var arrived = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        EventHandler<FrameReceipt>? handler = null;
        try
        {
            lock (_gate)
            {
                if (_state != CaptureLifecycle.Ready || _item is null || _nativeSession is null
                    || SelectedSource is null || MonotonicMilliseconds() >= _authorizationExpiresAtMonotonicMilliseconds)
                    throw new InvalidDataException("Current source sharing authorization is unavailable.");
                source = SelectedSource; expires = _authorizationExpiresAtMonotonicMilliseconds;
                handler = (_, frame) =>
                {
                    if (frame.SourceId == source.SourceId && frame.CaptureEpoch == source.CaptureEpoch)
                        arrived.TrySetResult();
                };
                FrameAvailable += handler;
                // Request new real pixels of the same authorized item. Keep
                // the original authorization expiry and capture epoch.
                StartCaptureLocked(_item.Size);
                pipelineStop = _captureStop!.Token;
            }
            using var bounded = CancellationTokenSource.CreateLinkedTokenSource(stop, pipelineStop);
            bounded.CancelAfter(TimeSpan.FromMilliseconds(Math.Max(1, Math.Min(2000, expires - MonotonicMilliseconds()))));
            await arrived.Task.WaitAsync(bounded.Token).ConfigureAwait(false);
            var frame = TryTakeLatestFrame();
            if (frame is null) throw new InvalidDataException("The selected source produced no current frame.");
            if (frame.Receipt.SourceId != source.SourceId || frame.Receipt.CaptureEpoch != source.CaptureEpoch
                || SelectedSource != source || _state != CaptureLifecycle.Ready)
            { frame.Dispose(); throw new InvalidDataException("The source changed during frame capture."); }
            return frame;
        }
        finally { if (handler is not null) FrameAvailable -= handler; }
    }

    public void Stop()
    {
        lock (_gate)
        {
            if (_state == CaptureLifecycle.Closed) return;
            InvalidateCaptureLocked(clearItem: true);
            SelectedSource = null;
            _captureEpoch++;
            _state = CaptureLifecycle.Closed;
        }
    }

    internal void StopSelectedSource(SelectedSourceReceipt expected)
    {
        lock (_gate)
        {
            if (SelectedSource == expected) Stop();
        }
    }

    private void StartCaptureLocked(SizeInt32 size)
    {
        if (_item is null) throw new InvalidOperationException("No selected source exists.");
        StopCapturePipelineLocked();
        _captureStop = new CancellationTokenSource();
        _frameSize = size;
        _device = Direct3DDeviceFactory.Create();
        _framePool = Direct3D11CaptureFramePool.CreateFreeThreaded(
            _device, DirectXPixelFormat.B8G8R8A8UIntNormalized, 2, size);
        _framePool.FrameArrived += OnFrameArrived;
        _nativeSession = _framePool.CreateCaptureSession(_item);
        _beforeNativeStart?.Invoke();
        Interlocked.Exchange(ref _lastFrameAtMonotonicMilliseconds, MonotonicMilliseconds());
        if (MonotonicMilliseconds() >= _authorizationExpiresAtMonotonicMilliseconds)
        {
            StopCapturePipelineLocked();
            throw new InvalidOperationException("Capture authorization expired during pipeline initialization.");
        }
        _nativeSession.StartCapture();
    }

    private SelectedSourceReceipt PrepareSelectedItemLocked(GraphicsCaptureItem item)
    {
        ReplaceItemLocked(item);
        var dimensions = item.Size;
        var sourceId = $"source-{Guid.NewGuid():N}";
        var revisionMaterial = $"{sourceId}\n{item.DisplayName}\n{dimensions.Width}\n{dimensions.Height}";
        var revision = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(revisionMaterial))).ToLowerInvariant();
        SelectedSource = new SelectedSourceReceipt(
            sourceId, item.DisplayName, "SELECTED_SURFACE",
            $"revision-{revision[..24]}", revision,
            checked((uint)dimensions.Width), checked((uint)dimensions.Height), _captureEpoch);
        _authorizationExpiresAtMonotonicMilliseconds = 0;
        _state = CaptureLifecycle.Ready;
        return SelectedSource;
    }

    private async void OnFrameArrived(Direct3D11CaptureFramePool sender, object args)
    {
        Interlocked.Exchange(ref _lastFrameAtMonotonicMilliseconds, MonotonicMilliseconds());
        if (!_copyGate.Wait(0)) return;
        byte[]? pixels = null;
        try
        {
            SelectedSourceReceipt? source;
            CancellationToken cancellationToken;
            lock (_gate)
            {
                if (_state != CaptureLifecycle.Ready || sender != _framePool) return;
                if (MonotonicMilliseconds() >= _authorizationExpiresAtMonotonicMilliseconds)
                    throw new InvalidDataException("Sharing authorization expired.");
                source = SelectedSource;
                cancellationToken = _captureStop?.Token ?? new CancellationToken(canceled: true);
            }
            if (source is null) return;

            using var frame = sender.TryGetNextFrame();
            if (frame is null) return;
            var width = frame.ContentSize.Width;
            var height = frame.ContentSize.Height;
            if (width <= 0 || height <= 0) return;
            var size = checked(width * height * 4);
            if (size > MaxFrameBytes) throw new InvalidDataException("Selected source frame exceeds the 32 MiB boundary.");

            using var bitmap = await SoftwareBitmap.CreateCopyFromSurfaceAsync(
                frame.Surface, BitmapAlphaMode.Premultiplied);
            cancellationToken.ThrowIfCancellationRequested();
            if (MonotonicMilliseconds() >= Interlocked.Read(ref _authorizationExpiresAtMonotonicMilliseconds))
                throw new InvalidDataException("Sharing authorization expired during frame copy.");
            var buffer = new Windows.Storage.Streams.Buffer(checked((uint)size));
            bitmap.CopyToBuffer(buffer);
            pixels = new byte[buffer.Length];
            using (var reader = DataReader.FromBuffer(buffer)) reader.ReadBytes(pixels);

            var receipt = new FrameReceipt(
                $"frame-{Guid.NewGuid():N}", source.SourceId, source.SourceRevision,
                source.CaptureEpoch, MonotonicMilliseconds(), checked((uint)width),
                checked((uint)height), "BGRA8_PREMULTIPLIED", pixels.Length,
                Convert.ToHexString(SHA256.HashData(pixels)).ToLowerInvariant());
            var captured = new CapturedFrame(receipt, pixels);
            pixels = null;
            lock (_gate)
            {
                if (_state == CaptureLifecycle.Ready && sender == _framePool
                    && MonotonicMilliseconds() >= _authorizationExpiresAtMonotonicMilliseconds)
                { captured.Dispose(); throw new InvalidDataException("Sharing authorization expired before frame publication."); }
                if (_state != CaptureLifecycle.Ready || sender != _framePool
                    || SelectedSource?.SourceId != source.SourceId
                    || SelectedSource.CaptureEpoch != source.CaptureEpoch)
                {
                    captured.Dispose();
                    return;
                }
                while (_frames.Count >= MaxFrames || _bufferBytes + receipt.SizeBytes > MaxBufferBytes)
                {
                    var stale = _frames.Dequeue();
                    _bufferBytes -= stale.Receipt.SizeBytes;
                    stale.Dispose();
                }
                _frames.Enqueue(captured);
                _bufferBytes += receipt.SizeBytes;
                if (frame.ContentSize.Width != _frameSize.Width || frame.ContentSize.Height != _frameSize.Height)
                {
                    _frameSize = frame.ContentSize;
                    sender.Recreate(_device!, DirectXPixelFormat.B8G8R8A8UIntNormalized, 2, frame.ContentSize);
                }
            }
            FrameAvailable?.Invoke(this, receipt);
        }
        catch (OperationCanceledException) { }
        catch (Exception error)
        {
            if (MarkSourceUnavailable(expectedPool: sender))
                NotifyCaptureFailed($"Capture frame unavailable: {error.Message}");
        }
        finally
        {
            if (pixels is not null) CryptographicOperations.ZeroMemory(pixels);
            _copyGate.Release();
        }
    }

    private bool MarkSourceUnavailable(GraphicsCaptureItem? expectedItem = null, Direct3D11CaptureFramePool? expectedPool = null, long? expectedEpoch = null)
    {
        lock (_gate)
        {
            if (_state is CaptureLifecycle.Closed or CaptureLifecycle.SourceUnavailable
                || expectedItem is not null && expectedItem != _item
                || expectedPool is not null && expectedPool != _framePool
                || expectedEpoch is not null && expectedEpoch != _captureEpoch) return false;
            InvalidateCaptureLocked(clearItem: true);
            SelectedSource = null;
            _captureEpoch++;
            _state = CaptureLifecycle.SourceUnavailable;
        }
        NotifySourceUnavailable();
        return true;
    }

    private void CheckFrameHealth(object? state)
    {
        long epoch;
        lock (_gate)
        {
            if (_state != CaptureLifecycle.Ready || _nativeSession is null
                || MonotonicMilliseconds() < _authorizationExpiresAtMonotonicMilliseconds) return;
            epoch = _captureEpoch;
        }
        // An unchanged window can legitimately emit no frames. Closure and
        // capture failures are separate from this finite authorization timer.
        if (MarkSourceUnavailable(expectedEpoch: epoch))
            NotifyCaptureFailed("Sharing authorization expired. Choose and authorize your source again.");
    }

    private void OnItemClosed(GraphicsCaptureItem sender, object args) => MarkSourceUnavailable(expectedItem: sender);

    private void NotifySourceUnavailable()
    {
        var handlers = SourceUnavailable;
        if (handlers is null) return;
        foreach (EventHandler handler in handlers.GetInvocationList())
        {
            try { handler(this, EventArgs.Empty); }
            catch { /* A presentation subscriber cannot prevent capture teardown. */ }
        }
    }

    private void NotifyCaptureFailed(string message)
    {
        var handlers = CaptureFailed;
        if (handlers is null) return;
        foreach (EventHandler<string> handler in handlers.GetInvocationList())
        {
            try { handler(this, message); }
            catch { /* A presentation subscriber cannot prevent capture teardown. */ }
        }
    }

    private void ReplaceItemLocked(GraphicsCaptureItem? next)
    {
        if (_item is not null)
        {
            _item.Closed -= OnItemClosed;
        }
        _item = next;
        if (_item is not null) _item.Closed += OnItemClosed;
    }

    private void InvalidateCaptureLocked(bool clearItem)
    {
        StopCapturePipelineLocked();
        ClearFramesLocked();
        if (clearItem) ReplaceItemLocked(null);
        if (clearItem) _authorizationExpiresAtMonotonicMilliseconds = 0;
    }

    private void StopCapturePipelineLocked()
    {
        _captureStop?.Cancel();
        if (_framePool is not null) _framePool.FrameArrived -= OnFrameArrived;
        _nativeSession?.Dispose();
        _framePool?.Dispose();
        _device?.Dispose();
        _nativeSession = null;
        _framePool = null;
        _device = null;
        _captureStop?.Dispose();
        _captureStop = null;
    }

    private void ClearFramesLocked()
    {
        while (_frames.Count > 0) _frames.Dequeue().Dispose();
        _bufferBytes = 0;
    }

    private static long MonotonicMilliseconds() => Environment.TickCount64;

    public void Dispose()
    {
        Stop();
        _frameWatchdog.Dispose();
        GC.SuppressFinalize(this);
    }

    [ComImport]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [Guid("3E68D4BD-7135-4D10-8018-9FB6D9F33FA1")]
    private interface IInitializeWithWindow
    {
        void Initialize(nint hwnd);
    }
}
