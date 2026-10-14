using System.Collections.Concurrent;
using System.Reflection;
using ScreenTutor;
using Windows.Graphics.Capture;
using Forms = System.Windows.Forms;
using Drawing = System.Drawing;

internal static class CaptureDeadlineTests
{
    internal static async Task RunAsync(bool expiresWhileQueued, Func<nint, GraphicsCaptureItem> createItem, bool expiresDuringSetup = false)
    {
        var ready = new TaskCompletionSource<Forms.Form>(TaskCreationOptions.RunContinuationsAsynchronously);
        Forms.Form? ownedForm = null;
        var cleanupRequested = 0;
        var sourceThread = new Thread(() =>
        {
            using var form = new Forms.Form { Text = "Screen Tutor owned deadline source", ClientSize = new Drawing.Size(320, 240) };
            ownedForm = form;
            var pulse = 0;
            using var timer = new Forms.Timer { Interval = 40 };
            timer.Tick += (_, _) => { pulse++; form.Invalidate(); };
            form.Paint += (_, paint) => paint.Graphics.FillRectangle(pulse % 2 == 0 ? Drawing.Brushes.Black : Drawing.Brushes.White, 0, 0, 320, 240);
            form.Shown += (_, _) => { if (Volatile.Read(ref cleanupRequested) != 0) { form.Close(); return; } timer.Start(); ready.TrySetResult(form); };
            Forms.Application.Run(form);
        });
        sourceThread.IsBackground = true;
        sourceThread.SetApartmentState(ApartmentState.STA);
        try
        {
            sourceThread.Start();
            var source = await ready.Task.WaitAsync(TimeSpan.FromSeconds(5));
            var item = (GraphicsCaptureItem)source.Invoke(new Func<GraphicsCaptureItem>(() => createItem(source.Handle)));
            var setupEntered = false;
            using var capture = expiresDuringSetup
                ? new CaptureSession(() => { setupEntered = true; Thread.Sleep(500); })
                : new CaptureSession();
            capture.BeginSelection();
            var selected = capture.PrepareAuthorizedTestSource(item);
            var frames = new ConcurrentQueue<FrameReceipt>();
            var firstFrame = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            capture.FrameAvailable += (_, receipt) => { frames.Enqueue(receipt); firstFrame.TrySetResult(); };
            var gate = typeof(CaptureSession).GetField("_gate", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(capture)!;
            using var locked = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
            var holder = new Thread(() =>
            {
                lock (gate) { locked.Set(); release.Wait(TimeSpan.FromSeconds(3)); }
            });
            holder.Start(); Require(locked.Wait(TimeSpan.FromSeconds(1)), "owned scheduling gate never locked");
            var issued = Environment.TickCount64;
            var expires = issued + (expiresWhileQueued || expiresDuringSetup ? 250 : 2000);
            var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var starting = Task.Run(() =>
            {
                entered.TrySetResult();
                try { capture.StartAuthorizedCapture(selected.SourceId, selected.SourceRevision, selected.CaptureEpoch, issued, expires); return (Exception?)null; }
                catch (Exception error) { return error; }
            });
            try
            {
                await entered.Task.WaitAsync(TimeSpan.FromSeconds(1));
                await Task.Delay(expiresDuringSetup ? 0 : expiresWhileQueued ? 500 : 700);
            }
            finally { release.Set(); Require(holder.Join(TimeSpan.FromSeconds(1)), "owned gate holder did not release"); }
            var failure = await starting.WaitAsync(TimeSpan.FromSeconds(3));
            if (expiresDuringSetup)
            {
                Require(setupEntered, "owned startup delay never entered real initialized capture pipeline");
                Require(failure is InvalidOperationException && failure.Message.Contains("expired", StringComparison.OrdinalIgnoreCase),
                    "native capture started after authorization expired during pipeline initialization");
                foreach (var field in new[] { "_nativeSession", "_framePool", "_device", "_captureStop" })
                    Require(typeof(CaptureSession).GetField(field, BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(capture) is null,
                        "expired startup retained pipeline resource: " + field);
                Require(frames.IsEmpty && capture.TryTakeLatestFrame() is null, "expired startup emitted pixels");
                Console.WriteLine("[actual startup expiry] real D3D/frame pool/session initialization plus500ms owned delay exhausts250ms grant; native start refused and pipeline disposed");
            }
            else if (expiresWhileQueued)
            {
                Require(failure is InvalidOperationException && failure.Message.Contains("expired", StringComparison.OrdinalIgnoreCase),
                    "capture started after its original authorization expired while queued");
                Require(frames.IsEmpty && capture.TryTakeLatestFrame() is null, "expired queued authorization emitted source pixels");
                var future = Environment.TickCount64 + 1000;
                Exception? clockFailure = null;
                try { capture.StartAuthorizedCapture(selected.SourceId, selected.SourceRevision, selected.CaptureEpoch, future, future + 1000); }
                catch (Exception error) { clockFailure = error; }
                Require(clockFailure is InvalidOperationException && clockFailure.Message.Contains("clock", StringComparison.OrdinalIgnoreCase)
                    && frames.IsEmpty && capture.TryTakeLatestFrame() is null, "future capture clock admitted source collection");
                Console.WriteLine("[actual queued capture expiry] 250ms original grant expires behind500ms gate delay; start refuses and emits zero pixels");
            }
            else
            {
                Require(failure is null, "still-current delayed capture refused: " + failure?.Message);
                await firstFrame.Task.WaitAsync(TimeSpan.FromSeconds(2));
                var wait = expires + 350 - Environment.TickCount64;
                if (wait > 0) await Task.Delay(TimeSpan.FromMilliseconds(wait));
                var receipts = frames.ToArray();
                Console.WriteLine($"[owned deadline measurement] issued={issued}, expires={expires}, first={receipts[0].CapturedAtMonotonicMilliseconds}, last={receipts[^1].CapturedAtMonotonicMilliseconds}, state={capture.State}");
                Require(receipts.Length > 0 && receipts.All(frame => frame.CapturedAtMonotonicMilliseconds < expires)
                    && capture.State == CaptureLifecycle.SourceUnavailable && capture.TryTakeLatestFrame() is null,
                    "delayed capture renewed original permission or retained pixels after original expiry");
                Console.WriteLine("[actual original capture deadline] real pre-expiry frames after700ms delay; original2000ms deadline stops/wipes without extension");
            }
        }
        finally
        {
            Interlocked.Exchange(ref cleanupRequested, 1);
            var source = ownedForm;
            if (source is { IsDisposed: false, IsHandleCreated: true })
            {
                try { source.BeginInvoke(source.Close); }
                catch (InvalidOperationException) when (source.IsDisposed || !source.IsHandleCreated) { }
            }
            Require(sourceThread.Join(TimeSpan.FromSeconds(3)), "owned deadline source did not close");
        }
    }

    private static void Require(bool condition, string message)
    { if (!condition) throw new InvalidOperationException(message); }
}
