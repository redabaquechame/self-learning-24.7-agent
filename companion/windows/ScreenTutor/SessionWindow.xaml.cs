using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;

namespace ScreenTutor;

public partial class SessionWindow : Window
{
    private CaptureSession _capture = new();
    private readonly GlobalShortcut _shortcut = new();
    private readonly SessionViewModel _session = new();
    private HwndSource? _windowSource;
    private bool _exitRequested;
    private bool _resourcesDisposed;
    private long _selectionGeneration;
    private NativeHostClient? _host;
    private Task _stopNotification = Task.CompletedTask;
    private Task _askTask = Task.CompletedTask;
    private Task _resumeTask = Task.CompletedTask;
    private bool _askInFlight;
    private SelectedSourceReceipt? _pendingSource;
    private long _pendingSourceGeneration;
    private Task _authorizationRetryTask = Task.CompletedTask;

    private void ClearPendingSource()
    {
        _pendingSource=null;
        RetryAuthorizationButton.Visibility=Visibility.Collapsed;
        RetryAuthorizationButton.IsEnabled=false;
    }

    private void ShowSourceApprovalPending(CaptureSession capture, SelectedSourceReceipt selected, long generation)
    {
        if(_exitRequested || _resourcesDisposed || capture!=_capture || generation!=_selectionGeneration
            || capture.State!=CaptureLifecycle.Ready || capture.SelectedSource!=selected) return;
        _pendingSource=selected;_pendingSourceGeneration=generation;
        SharingIndicator.Text="Source selected; not sharing";
        SourceName.Text=selected.DisplayName;
        Status.Text="Waiting for Fleet approval. Your source stays selected without sharing. After approval, choose Retry authorization.";
        RetryAuthorizationButton.Visibility=Visibility.Visible;
        RetryAuthorizationButton.IsEnabled=_host is {Ready:true};
        StopButton.IsEnabled=true;PauseButton.IsEnabled=false;AskButton.IsEnabled=false;
        SelectButton.IsEnabled=true;
    }

    private async void RetryAuthorization_Click(object sender, RoutedEventArgs e)
    {
        if(!_authorizationRetryTask.IsCompleted) return;
        _authorizationRetryTask=RetryPendingSourceAsync();
        await _authorizationRetryTask;
    }

    private async Task RetryPendingSourceAsync()
    {
        var capture=_capture;var selected=_pendingSource;var generation=_selectionGeneration;var host=_host;
        if(selected is null || host is not {Ready:true} || generation!=_pendingSourceGeneration
            || capture.State!=CaptureLifecycle.Ready || capture.SelectedSource!=selected) return;
        RetryAuthorizationButton.IsEnabled=false;SelectButton.IsEnabled=false;
        Status.Text="Checking Fleet approval for this same selected source.";
        try
        {
            await host.AuthorizeCaptureAsync(capture,selected,CancellationToken.None);
            if(_exitRequested || _resourcesDisposed || capture!=_capture || generation!=_selectionGeneration
                || capture.SelectedSource!=selected) return;
            ClearPendingSource();
            PauseButton.Content="Pause";PauseButton.IsEnabled=true;StopButton.IsEnabled=true;
            SharingIndicator.Text="Sharing one selected source";SourceName.Text=selected.DisplayName;
            Status.Text="Sharing the selected source. Ask becomes available after its first current frame.";
        }
        catch(SourceApprovalPendingException)
        {
            ShowSourceApprovalPending(capture,selected,generation);
        }
        catch(Exception error)
        {
            if(!_exitRequested && !_resourcesDisposed && capture==_capture && generation==_selectionGeneration)
            {
                capture.Stop();ShowUnavailable();
                Status.Text="Source authorization unavailable: "+error.Message;
            }
        }
        finally
        {
            if(!_exitRequested && !_resourcesDisposed && capture==_capture && generation==_selectionGeneration)
                SelectButton.IsEnabled=true;
        }
    }

    private long _guidanceGeneration;
    private string? _answerFrameDigest;
    private System.Text.Json.JsonElement? _teachingBinding;
    private TeachingCanvas? _teachingCanvas;
    private System.Windows.Threading.DispatcherTimer? _teachingExpiry;

    private void ClearTeachingScene()
    {
        _teachingBinding = null;
        _teachingExpiry?.Stop(); _teachingExpiry = null;
        _teachingCanvas?.Stop(); _teachingCanvas = null;
        TeachingSceneHost.Content = null;
        TeachingSceneAlternative.Text = ""; TeachingSceneQualification.Text = "";
        TeachingSceneBlock.Visibility = Visibility.Collapsed;
    }

    private void RetireTeachingScene(System.Text.Json.JsonElement binding)
    {
        if(_teachingBinding is not { } current || !System.Text.Json.JsonElement.DeepEquals(current,binding)) return;
        ClearTeachingScene();
        Status.Text="Teaching content authorization changed. Ask again for current content.";
    }

    private bool ShowTeachingScene(System.Text.Json.JsonElement presentation,
        System.Text.Json.JsonElement observation, string requestId)
    {
        ClearTeachingScene();
        var expiry=presentation.GetProperty("expires_at_monotonic_ms").GetInt64();
        var binding=presentation.GetProperty("binding");
        if (_host is null || !_host.IsPresentationCurrent(binding) || _session.Intent!=CompanionIntent.Teach || expiry<=Environment.TickCount64
            || _capture.State!=CaptureLifecycle.Ready || _capture.SelectedSource is not { } source
            || source.SourceId!=binding.GetProperty("source_id").GetString()
            || source.SourceRevision!=binding.GetProperty("source_revision").GetString()
            || source.CaptureEpoch!=binding.GetProperty("capture_epoch").GetInt64()
            || requestId!=binding.GetProperty("request_id").GetString()
            // Native frame continuity uses the admitted BGRA digest; the host
            // observation/presentation separately binds the encoded PNG digest.
            || _session.ObservationRevision!=_answerFrameDigest) return false;
        foreach(var name in new[]{"session_id","user_id","tenant_id","project_id","observation_id","source_id","source_revision","geometry_revision","content_sha256","consent_revision"})
            if(binding.GetProperty(name).GetString()!=observation.GetProperty(name).GetString())return false;
        var canvas=new TeachingCanvas();
        canvas.LoadRenderModel(System.Text.Json.JsonSerializer.SerializeToUtf8Bytes(presentation.GetProperty("render_model")));
        canvas.BeginPracticeInk(binding.GetProperty("content_sha256").GetString()!);
        if(expiry<=Environment.TickCount64){canvas.Stop();return false;}
        _teachingBinding=binding.Clone();
        _teachingCanvas=canvas; TeachingSceneHost.Content=canvas;
        TeachingSceneAlternative.Text=canvas.TextAlternative;
        TeachingSceneQualification.Text=presentation.GetProperty("qualification").GetString()=="LOCAL_ONLY"
            ? "Local demonstration - unqualified content" : "Reviewed teaching content - learning outcome unverified";
        TeachingSceneBlock.Visibility=Visibility.Visible;
        TeachingSceneBlock.BringIntoView();
        var generation=_guidanceGeneration;
        _teachingExpiry=new System.Windows.Threading.DispatcherTimer { Interval=TimeSpan.FromMilliseconds(100) };
        _teachingExpiry.Tick+=(_,_)=>
        {
            if(expiry<=Environment.TickCount64 || generation!=_guidanceGeneration || _capture.State!=CaptureLifecycle.Ready)
                ClearTeachingScene();
        };
        _teachingExpiry.Start();
        return true;
    }

    private void ResetPractice_Click(object sender, RoutedEventArgs e)
    {
        _teachingCanvas?.ResetPracticeInk();
        Status.Text="Your scratch notes were cleared.";
    }

    private void ClearAnswer()
    {
        ClearTeachingScene();
        _answerFrameDigest = null;
        AnswerText.Text = ""; AnswerEvidence.Text = "";
        OnboardingJourney.InvalidateAnswerProgress();
    }

    private async void Ask_Click(object sender, RoutedEventArgs e)
    {
        if (_askInFlight) return;
        _askTask = AskAsync();
        await _askTask;
    }

    private async Task AskAsync()
    {
        Dispatcher.VerifyAccess();
        if (_askInFlight) return;
        if (string.IsNullOrWhiteSpace(Question.Text)) { Status.Text = "Enter a question about your selected source."; Question.Focus(); return; }
        if (_pendingSource is not null || _host is not { Ready: true } host || _capture.State != CaptureLifecycle.Ready || _capture.SelectedSource is not { } source)
        { Status.Text = "Choose and authorize a source before asking."; return; }
        if (_session.Intent == CompanionIntent.Collaborate)
        { Status.Text = "The task collaboration route still needs host integration."; return; }
        var capture = _capture; var selection = _selectionGeneration; var guidance = _guidanceGeneration;
        var question = Question.Text; var requestId = "question-" + Guid.NewGuid().ToString("N");
        _askInFlight = true; AskButton.IsEnabled = false; ClearAnswer();
        try
        {
            Status.Text = "Reading your selected source…";
            using var frame = await capture.TakeCurrentFrameAsync(CancellationToken.None);
            var digest = frame.Receipt.ContentSha256;
            Status.Text = "Reading your selected source…";
            var observation = await host.SendFrameAsync(frame, CancellationToken.None);
            if (_exitRequested || _resourcesDisposed || capture != _capture || selection != _selectionGeneration
                || guidance != _guidanceGeneration || capture.State != CaptureLifecycle.Ready) return;
            var intent = _session.Intent switch { CompanionIntent.Teach => "LEARN", CompanionIntent.Assess => "ASSESS",
                CompanionIntent.Show => "FINISH", _ => "UNDERSTAND" };
            Status.Text = "Waiting for your source explanation…";
            var answer = await host.SendTeachingQuestionAsync(observation, requestId, question, intent, "en-CA", CancellationToken.None);
            var instruction = answer.Instruction;
            if (_exitRequested || _resourcesDisposed || capture != _capture || source != capture.SelectedSource
                || selection != _selectionGeneration || guidance != _guidanceGeneration
                || capture.State != CaptureLifecycle.Ready) return;
            if (_session.ObservationRevision != digest)
            {
                ClearAnswer();
                Status.Text = "Your source changed while the answer was being prepared. Ask again using the current view.";
                return;
            }
            _answerFrameDigest = digest;
            AnswerText.Text = instruction.GetProperty("answer").GetString();
            var claims = instruction.GetProperty("claims").EnumerateArray();
            AnswerEvidence.Text = "Source snapshot: " + source.DisplayName + " (" + observation.GetProperty("captured_at_utc").GetString() + ")\n" + string.Join("\n", claims.Select(claim =>
                claim.GetProperty("text").GetString() + " — uncertainty " + claim.GetProperty("uncertainty").GetDouble().ToString("P0")));
            var sceneShown=answer.Presentation is { } presentation && ShowTeachingScene(presentation,observation,requestId);
            Status.Text = _session.Intent==CompanionIntent.Teach && !sceneShown
                ? "Your explanation is ready. A teaching diagram is unavailable for this answer."
                : "Your explanation is ready.";
            OnboardingJourney.TryCompleteStep("ASK");
        }
        catch (Exception error)
        {
            if (!_exitRequested && !_resourcesDisposed && capture == _capture && selection == _selectionGeneration && guidance == _guidanceGeneration)
            {
                ClearAnswer();
                Status.Text = error is OperationCanceledException && host.Ready && capture.State == CaptureLifecycle.Ready
                    ? "The request timed out. Ask again using the current source."
                    : error is InvalidDataException ? error.Message : "The answer connection is unavailable. Choose your source again.";
            }
        }
        finally
        {
            _askInFlight = false;
            if (!_exitRequested && !_resourcesDisposed)
                AskButton.IsEnabled = _host is { Ready: true } && _capture.State == CaptureLifecycle.Ready;
        }
    }

    internal void AttachHost(NativeHostClient host)
    {
        Dispatcher.VerifyAccess();
        if (_exitRequested || _resourcesDisposed || !host.Ready || _host is not null && _host != host)
            throw new InvalidOperationException("Companion host is unavailable or already bound.");
        _host = host;
        host.PresentationRetired += binding =>
        {
            if(Dispatcher.HasShutdownStarted || Dispatcher.HasShutdownFinished) return;
            Dispatcher.BeginInvoke((Action)(() =>
            {
                if(_host!=host || _exitRequested || _resourcesDisposed) return;
                RetireTeachingScene(binding);
            }));
        };
        host.SourceControl += (kind, capture) =>
        {
            var generation = Volatile.Read(ref _selectionGeneration);
            if (Dispatcher.HasShutdownStarted || Dispatcher.HasShutdownFinished) return;
            Dispatcher.BeginInvoke((Action)(() =>
            {
                if (_exitRequested || _resourcesDisposed || _host != host || generation != _selectionGeneration
                    || capture is not null && capture != _capture) return;
                ClearPendingSource();
                _guidanceGeneration++; _selectionGeneration++; ClearAnswer();
                OnboardingJourney.InvalidateSourceProgress();
                _capture.Stop(); _session.StopSharing();
                AskButton.IsEnabled = false; PauseButton.IsEnabled = false; StopButton.IsEnabled = false;
                SelectButton.IsEnabled = true;
                SharingIndicator.Text = kind == "STOP" ? "Not sharing" : "Source unavailable";
                SourceName.Text = "Choose and authorize your source again.";
                Status.Text = kind == "DISCONNECTED" ? "The host connection is unavailable. Sharing has stopped." : "Sharing authorization changed. Sharing has stopped.";
            }));
        };
    }

    private void RetireHostCapture()
    {
        var host = _host;
        if (host is null) return;
        host.StopCapture();
        _stopNotification = NotifySourceStopAsync(host, _selectionGeneration);
    }

    private async Task NotifySourceStopAsync(NativeHostClient host, long generation)
    {
        try { await host.NotifySourceStoppedAsync(); }
        catch (Exception)
        {
            if (!_exitRequested && !_resourcesDisposed && generation == _selectionGeneration)
                Status.Text = "Sharing stopped. The host connection is unavailable.";
        }
    }

    public SessionWindow()
    {
        InitializeComponent();
        DataContext = _session;
        OnboardingJourney.ActionRequested += OnboardingActionRequested;
        _session.ConfigureCapabilities(microphoneAvailable: false, providerAvailable: false);
        Question.TextChanged += (_, _) => _session.Draft = Question.Text;
        BindCaptureEvents(_capture);
        SourceInitialized += (_, _) => RegisterShortcut();
        Activated += (_, _) =>
        {
            if (!_exitRequested && !_resourcesDisposed && WindowState != WindowState.Minimized)
                _session.ReopenPanel();
        };
    }

    private void OnboardingActionRequested(object? sender, string step)
    {
        if (_exitRequested || _resourcesDisposed) return;
        switch (step)
        {
            case "SUMMON": SummonPanel(); break;
            case "SELECT" when SelectButton.IsEnabled: SelectSource_Click(SelectButton, new RoutedEventArgs()); break;
            case "ASK" when AskButton.IsEnabled: Ask_Click(AskButton, new RoutedEventArgs()); break;
            case "SHOW": Status.Text = "Visual guidance and practice are unavailable in this build. You can keep asking questions or stop sharing."; break;
            case "STOP" when StopButton.IsEnabled: Stop_Click(StopButton, new RoutedEventArgs()); break;
        }
    }

    private void BindCaptureEvents(CaptureSession capture)
    {
        capture.SourceUnavailable += (_, _) => PostForCapture(capture, ShowUnavailable);
        capture.CaptureFailed += (_, message) => PostForCapture(capture, () => Status.Text = message);
        FrameReceipt? latest = null;
        int posted = 0;
        capture.FrameAvailable += (_, frame) =>
        {
            if (!IsCurrentCapture(capture)) return;
            Interlocked.Exchange(ref latest, frame);
            if (Interlocked.Exchange(ref posted, 1) != 0) return;
            PostForCapture(capture, () =>
            {
                Interlocked.Exchange(ref posted, 0);
                var current = Interlocked.Exchange(ref latest, null);
                if (current is not null && capture.State == CaptureLifecycle.Ready
                    && capture.SelectedSource?.SourceId == current.SourceId
                    && capture.SelectedSource.SourceRevision == current.SourceRevision
                    && capture.SelectedSource.CaptureEpoch == current.CaptureEpoch)
                {
                    SharingIndicator.Text = "Sharing one selected source";
                    PauseButton.IsEnabled = true;
                    AskButton.IsEnabled = !_askInFlight && _host is { Ready: true };
                    if (_host is { Ready: true }) OnboardingJourney.TryCompleteStep("SELECT");
                    if (_answerFrameDigest is not null && _answerFrameDigest != current.ContentSha256)
                    {
                        ClearAnswer();
                        Status.Text = "Your source changed. Ask again using the current view.";
                    }
                    var firstSourceFrame = _session.ObservationRevision is null;
                    _session.BindObservation(current.ContentSha256);
                    if (firstSourceFrame && !_askInFlight && _answerFrameDigest is null)
                        Status.Text = "Your selected source is ready. You can pause or stop sharing at any time.";
                }
            }, () =>
            {
                Interlocked.Exchange(ref posted, 0);
                Interlocked.Exchange(ref latest, null);
            });
        };
    }

    private bool IsCurrentCapture(CaptureSession capture) => !_exitRequested && !_resourcesDisposed
        && ReferenceEquals(capture, _capture) && capture.State != CaptureLifecycle.Closed;

    private void PostForCapture(CaptureSession capture, Action display, Action? discard = null)
    {
        if (!IsCurrentCapture(capture) || Dispatcher.HasShutdownStarted || Dispatcher.HasShutdownFinished)
        {
            discard?.Invoke();
            return;
        }
        var generation = Volatile.Read(ref _selectionGeneration);
        void DisplayCurrent()
        {
            if (IsCurrentCapture(capture) && generation == _selectionGeneration) display();
            else discard?.Invoke();
        }
        if (Dispatcher.CheckAccess()) DisplayCurrent();
        else Dispatcher.BeginInvoke((Action)DisplayCurrent);
    }

    internal CaptureSession PrepareCaptureSelection()
    {
        if (_exitRequested || _resourcesDisposed)
            throw new InvalidOperationException("An exited companion cannot select a source.");
        ClearPendingSource();
        _selectionGeneration++;
        _guidanceGeneration++; ClearAnswer();
        OnboardingJourney.InvalidateSourceProgress();
        if (_capture.SelectedSource is not null) RetireHostCapture();
        if (_capture.State == CaptureLifecycle.Closed)
        {
            _capture.Dispose();
            _capture = new CaptureSession();
            BindCaptureEvents(_capture);
        }
        _session.StopSharing();
        PauseButton.IsEnabled = false; StopButton.IsEnabled = false; AskButton.IsEnabled = false;
        PauseButton.Content = "Pause";
        SharingIndicator.Text = "Not sharing";
        SourceName.Text = "Choose one source; fresh authorization is required.";
        _capture.BeginSelection();
        return _capture;
    }

    private void RegisterShortcut()
    {
        var hwnd = new WindowInteropHelper(this).Handle;
        _windowSource = HwndSource.FromHwnd(hwnd);
        _windowSource.AddHook(WindowMessage);
        const uint controlShift = 0x0002 | 0x0004;
        const uint keySpace = 0x20;
        if (!_shortcut.TryRegister(hwnd, controlShift, keySpace))
        {
            Status.Text = _shortcut.ConflictReason;
            AlternateShortcutButton.Visibility = Visibility.Visible;
        }
    }

    private void AlternateShortcut_Click(object sender, RoutedEventArgs e)
    {
        var hwnd = new WindowInteropHelper(this).Handle;
        const uint controlShift = 0x0002 | 0x0004;
        const uint keyF12 = 0x7B;
        if (_shortcut.TryRegister(hwnd, controlShift, keyF12))
        {
            AlternateShortcutButton.Visibility = Visibility.Collapsed;
            Status.Text = "Shortcut changed to Ctrl+Shift+F12.";
        }
        else Status.Text = _shortcut.ConflictReason;
    }

    private nint WindowMessage(nint hwnd, int message, nint wParam, nint lParam, ref bool handled)
    {
        const int wmHotkey = 0x0312;
        if (message == wmHotkey && wParam == GlobalShortcut.HotkeyId)
        {
            SummonPanel();
            handled = true;
        }
        return 0;
    }

    private async void SelectSource_Click(object sender, RoutedEventArgs e)
        => await SelectSourceAsync();

    internal async Task SelectSourceAsync(
        Func<CaptureSession, nint, Task<SelectedSourceReceipt?>>? picker = null)
    {
        SelectButton.IsEnabled = false;
        CaptureSession? capture = null;
        long attempt = -1;
        try
        {
            capture = PrepareCaptureSelection();
            attempt = _selectionGeneration;
            var ownerWindow = new WindowInteropHelper(this).Handle;
            var selected = await (picker is null
                ? capture.PickSingleSourceAsync(ownerWindow) : picker(capture, ownerWindow));
            if (_exitRequested || _resourcesDisposed || attempt != _selectionGeneration || !ReferenceEquals(capture, _capture)
                || capture.State == CaptureLifecycle.Closed) return;
            if (selected is null) { capture.Stop(); ShowUnavailable(); return; }
            if (capture.State != CaptureLifecycle.Ready || capture.SelectedSource != selected)
                throw new InvalidDataException("Picker receipt does not match the current native selection.");
            SharingIndicator.Text = "Source selected; not sharing yet";
            SourceName.Text = selected.DisplayName;
            _session.SelectSource(selected.SourceId, selected.SourceRevision, selected.DisplayName);
            PauseButton.IsEnabled = false;
            StopButton.IsEnabled = true;
            Status.Text = "Source selected. Capture starts only after the authenticated host authorizes this exact source.";
            if (_host is { Ready: true } host)
            {
                await host.AuthorizeCaptureAsync(capture, selected, CancellationToken.None);
                if (_exitRequested || _resourcesDisposed || attempt != _selectionGeneration
                    || !ReferenceEquals(capture, _capture) || capture.SelectedSource != selected) return;
                Status.Text = "Sharing the selected source. Ask will be available when its answer service is connected.";
            }
        }
        catch (SourceApprovalPendingException)
        {
            if(capture is not null && capture.SelectedSource is { } pending)
                ShowSourceApprovalPending(capture,pending,attempt);
        }
        catch (Exception error)
        {
            if (!_exitRequested && !_resourcesDisposed && (capture is null
                || ReferenceEquals(capture, _capture) && attempt == _selectionGeneration))
            {
                capture?.Stop();
                Status.Text = $"Source selection unavailable: {error.Message}";
                ShowUnavailable();
            }
        }
        finally
        {
            if (!_exitRequested && !_resourcesDisposed && (capture is null
                || ReferenceEquals(capture, _capture) && attempt == _selectionGeneration))
                SelectButton.IsEnabled = true;
        }
    }

    private async void Pause_Click(object sender, RoutedEventArgs e)
    {
        if (!_resumeTask.IsCompleted) return;
        _guidanceGeneration++; ClearAnswer();
        if (_capture.State == CaptureLifecycle.Paused)
        {
            _resumeTask = ResumeSharingAsync();
            await _resumeTask;
        }
        else
        {
            _capture.Pause(); PauseButton.Content = "Resume"; SharingIndicator.Text = "Sharing paused";
            OnboardingJourney.InvalidateSourceProgress();
            AskButton.IsEnabled = false; _session.StopSharing();
            if (_host is { Ready: true } host)
            {
                host.PauseCapture();
                _stopNotification = NotifySourcePauseAsync(host, _selectionGeneration);
            }
            Status.Text = "Sharing paused. Resume requires fresh authorization.";
        }
    }

    private async Task NotifySourcePauseAsync(NativeHostClient host, long generation)
    {
        try { await host.NotifySourcePausedAsync(); }
        catch (Exception)
        {
            if (!_exitRequested && !_resourcesDisposed && generation == _selectionGeneration)
                ShowUnavailable();
        }
    }

    private async Task ResumeSharingAsync()
    {
        var capture = _capture; var host = _host;
        var attempt = ++_selectionGeneration;
        PauseButton.IsEnabled = false; AskButton.IsEnabled = false;
        Status.Text = "Checking fresh sharing authorization…";
        SelectedSourceReceipt? source = null;
        try
        {
            if (host is not { Ready: true }) throw new InvalidDataException("The host connection is unavailable.");
            source = capture.PrepareResumeAuthorization();
            OnboardingJourney.InvalidateSourceProgress();
            _session.SelectSource(source.SourceId, source.SourceRevision, source.DisplayName);
            await host.AuthorizeCaptureAsync(capture, source, CancellationToken.None);
            if (_exitRequested || _resourcesDisposed || capture != _capture || attempt != _selectionGeneration
                || capture.State != CaptureLifecycle.Ready || capture.SelectedSource != source) return;
            PauseButton.Content = "Pause"; PauseButton.IsEnabled = true; StopButton.IsEnabled = true;
            SharingIndicator.Text = "Sharing one selected source";
            SourceName.Text = source.DisplayName;
            Status.Text = "Fresh sharing authorization confirmed. Waiting for your source frame…";
        }
        catch (SourceApprovalPendingException)
        {
            if (source is not null) ShowSourceApprovalPending(capture, source, attempt);
        }
        catch (Exception)
        {
            if (!_exitRequested && !_resourcesDisposed && capture == _capture && attempt == _selectionGeneration)
            {
                ShowUnavailable();
                Status.Text = "Sharing could not resume. Choose and authorize your source again.";
            }
        }
    }

    private void Stop_Click(object sender, RoutedEventArgs e)
    {
        ClearPendingSource();
        var journeyStopped = OnboardingJourney.TryCompleteStep("STOP");
        _guidanceGeneration++; ClearAnswer();
        if (!journeyStopped) OnboardingJourney.InvalidateSourceProgress();
        RetireHostCapture();
        _selectionGeneration++;
        _capture.Stop();
        _session.StopSharing();
        SharingIndicator.Text = "Not sharing";
        SourceName.Text = "No source selected";
        PauseButton.Content = "Pause";
        PauseButton.IsEnabled = false; StopButton.IsEnabled = false; AskButton.IsEnabled = false;
        SelectButton.IsEnabled = true;
        Status.Text = "Sharing stopped locally.";
    }

    private void Intent_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string value }
            || !Enum.TryParse<CompanionIntent>(value, out var intent)) return;
        _session.SetIntent(intent);
        Status.Text = _session.IntentDescription;
        Question.Focus();
    }

    private void StopSpeech_Click(object sender, RoutedEventArgs e)
    {
        Status.Text = "Assistant speech is not connected in this build.";
        Question.Focus();
    }

    private void CancelTask_Click(object sender, RoutedEventArgs e)
    {
        Status.Text = _session.TaskId is null ? "No Fleet task is connected to this companion."
            : "Task cancellation is unavailable here. Use the task controls in Fleet.";
        Question.Focus();
    }

    private void ShowUnavailable()
    {
        ClearPendingSource();
        _guidanceGeneration++; ClearAnswer();
        OnboardingJourney.InvalidateSourceProgress();
        RetireHostCapture();
        _selectionGeneration++;
        _session.StopSharing();
        SharingIndicator.Text = "Source unavailable";
        SourceName.Text = "Choose the source again; no fallback source was selected.";
        PauseButton.IsEnabled = false; StopButton.IsEnabled = false; AskButton.IsEnabled = false;
        SelectButton.IsEnabled = true;
    }

    protected override void OnClosing(CancelEventArgs e)
    {
        _session.Draft = Question.Text;
        _session.ClosePanel();
        base.OnClosing(e);
        if (_exitRequested) return;
        e.Cancel = true;
        // Keep a taskbar recovery route if no summon shortcut could register.
        if (IsLoaded && !_shortcut.IsRegistered) WindowState = WindowState.Minimized;
        else Hide();
    }

    internal void SummonPanel()
    {
        if (_exitRequested || _resourcesDisposed) return;
        _session.ReopenPanel();
        Question.Text = _session.Draft;
        if (WindowState == WindowState.Minimized) WindowState = WindowState.Normal;
        Show(); Activate(); Topmost = true; Topmost = false; Question.Focus();
        OnboardingJourney.TryCompleteStep("SUMMON");
    }

    private void Exit_Click(object sender, RoutedEventArgs e) => ExitCompanion();

    internal void ExitCompanion()
    {
        ClearPendingSource();
        if (_resourcesDisposed) return;
        _exitRequested = true;
        Close();
        if (!_resourcesDisposed) _exitRequested = false;
    }

    protected override void OnClosed(EventArgs e)
    {
        if (!_resourcesDisposed)
        {
            _selectionGeneration++;
            _guidanceGeneration++;
            ClearAnswer();
            _resourcesDisposed = true;
            _host?.Stop();
            _windowSource?.RemoveHook(WindowMessage);
            _capture.Dispose(); _shortcut.Dispose();
            _session.StopAll();
        }
        base.OnClosed(e);
    }
}
