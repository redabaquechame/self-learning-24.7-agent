using System.Windows;
using System.IO;

namespace ScreenTutor;

public partial class App : Application
{
    private readonly CancellationTokenSource _startupStop = new();
    internal NativeHostClient? HostConnection { get; private set; }

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        var window = new SessionWindow { Title = "Screen Tutor — Host not connected" };
        MainWindow = window; window.Show();
        if (e.Args is not ["--native-host-stdin"]) return;
        window.Title = "Screen Tutor — Connecting";
        try
        {
            var host = await NativeHostClient.OpenAsync(Console.OpenStandardInput(), _startupStop.Token);
            if (_startupStop.IsCancellationRequested) { await host.DisposeAsync(); return; }
            HostConnection = host;
            window.AttachHost(host);
            host.StartReceiving();
            window.Title = "Screen Tutor";
        }
        catch (InvalidDataException)
        {
            if (!_startupStop.IsCancellationRequested) window.Title = "Screen Tutor — Host unavailable";
        }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _startupStop.Cancel(); HostConnection?.Stop();
        base.OnExit(e);
    }
}
