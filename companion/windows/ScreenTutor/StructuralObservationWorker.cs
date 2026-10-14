using System.IO;

namespace ScreenTutor;

internal sealed record StructuralObservation(
    string SourceId,
    long CaptureEpoch,
    IReadOnlyList<string> Labels);

/// <summary>
/// Runs observation-only UI Automation work away from the WPF dispatcher.
/// A provider that ignores cancellation may retain its background thread, but
/// it cannot hold capture locks, publish a late result, or delay local Stop.
/// </summary>
internal sealed class StructuralObservationWorker : IDisposable
{
    public const int MaxLabels = 256;
    public const int MaxLabelCharacters = 512;

    private readonly CancellationTokenSource _stop = new();
    private int _inFlight;
    private int _poisoned;

    internal bool IsPoisoned => Volatile.Read(ref _poisoned) != 0;

    internal async Task<StructuralObservation> ObserveAsync(
        Func<CancellationToken, StructuralObservation> observe,
        TimeSpan timeout,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(observe);
        if (timeout <= TimeSpan.Zero || timeout > TimeSpan.FromSeconds(10))
            throw new ArgumentOutOfRangeException(nameof(timeout), "Observation deadline must be within ten seconds.");
        _stop.Token.ThrowIfCancellationRequested();
        if (IsPoisoned)
            throw new InvalidOperationException("Structural observation worker is unavailable after a provider timeout.");
        if (Interlocked.CompareExchange(ref _inFlight, 1, 0) != 0)
            throw new InvalidOperationException("Only one structural observation may run at a time.");

        using var callStop = CancellationTokenSource.CreateLinkedTokenSource(
            _stop.Token, cancellationToken);
        var completion = new TaskCompletionSource<StructuralObservation>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var thread = new Thread(() =>
        {
            try
            {
                var result = Validate(observe(callStop.Token));
                if (!callStop.IsCancellationRequested) completion.TrySetResult(result);
            }
            catch (OperationCanceledException) when (callStop.IsCancellationRequested)
            {
                completion.TrySetCanceled(callStop.Token);
            }
            catch (Exception error)
            {
                completion.TrySetException(error);
            }
            finally
            {
                Interlocked.Exchange(ref _inFlight, 0);
            }
        })
        {
            IsBackground = true,
            Name = "ScreenTutor.UIA.Observer",
        };
        thread.SetApartmentState(ApartmentState.MTA);
        thread.Start();

        try
        {
            return await completion.Task.WaitAsync(timeout, callStop.Token).ConfigureAwait(false);
        }
        catch (TimeoutException)
        {
            Interlocked.Exchange(ref _poisoned, 1);
            callStop.Cancel();
            throw new TimeoutException("Structural observation provider exceeded its deadline; the worker is closed to further calls.");
        }
    }

    internal void Stop() => _stop.Cancel();

    private static StructuralObservation Validate(StructuralObservation value)
    {
        ArgumentNullException.ThrowIfNull(value);
        if (string.IsNullOrWhiteSpace(value.SourceId) || value.SourceId.Length > 160)
            throw new InvalidDataException("Structural observation source identity is invalid.");
        if (value.CaptureEpoch < 0 || value.Labels.Count > MaxLabels)
            throw new InvalidDataException("Structural observation bounds are invalid.");
        if (value.Labels.Any(label => string.IsNullOrWhiteSpace(label)
                                      || label.Length > MaxLabelCharacters))
            throw new InvalidDataException("Structural observation label is invalid.");
        return value;
    }

    public void Dispose()
    {
        Stop();
        _stop.Dispose();
        GC.SuppressFinalize(this);
    }
}
