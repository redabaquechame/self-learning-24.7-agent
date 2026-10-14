using System.ComponentModel;
using System.IO;
using System.Runtime.CompilerServices;
using System.Text.RegularExpressions;

namespace ScreenTutor;

public enum CompanionIntent { Explain, Show, Teach, Assess, Collaborate }

/// <summary>
/// Owns visible companion session semantics. Draft and goal survive harmless
/// panel closure, while source-derived observations are invalidated whenever
/// the selected source changes. Each stop/cancel operation has one scope.
/// </summary>
public sealed class SessionViewModel : INotifyPropertyChanged
{
    private static readonly Regex Identifier = new(
        "^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", RegexOptions.CultureInvariant);
    private string _draft = string.Empty;
    private string _learningGoal = string.Empty;
    private string? _sourceId;
    private string? _sourceRevision;
    private string? _sourceDisplayName;
    private string? _observationRevision;
    private string? _taskId;

    public event PropertyChangedEventHandler? PropertyChanged;

    public CompanionIntent Intent { get; private set; } = CompanionIntent.Explain;
    public bool PanelOpen { get; private set; } = true;
    public bool SharingActive { get; private set; }
    public bool SpeechPlaying { get; private set; }
    public bool TaskRunning => _taskId is not null;
    public bool TextInputAvailable => true;
    public bool MicrophoneAvailable { get; private set; }
    public bool ProviderAvailable { get; private set; }
    public bool ReducedMotion { get; private set; }
    public double TextScale { get; private set; } = 1.0;
    public long SourceEpoch { get; private set; }
    public long SpeechEpoch { get; private set; }
    public string? SourceId => _sourceId;
    public string? SourceRevision => _sourceRevision;
    public string? SourceDisplayName => _sourceDisplayName;
    public string? ObservationRevision => _observationRevision;
    public string? TaskId => _taskId;
    public string FocusTarget { get; private set; } = "Question";

    public string Draft
    {
        get => _draft;
        set
        {
            if (value is null || value.Length > 8192)
                throw new InvalidDataException("Draft is outside bounds.");
            Set(ref _draft, value);
        }
    }

    public string LearningGoal
    {
        get => _learningGoal;
        set
        {
            if (value is null || value.Length > 1024)
                throw new InvalidDataException("Learning goal is outside bounds.");
            Set(ref _learningGoal, value);
        }
    }

    public string CapabilityMessage => (MicrophoneAvailable, ProviderAvailable) switch
    {
        (true, true) => "Text and optional push-to-talk are available.",
        (false, true) => "Microphone unavailable. Type your question; all teaching controls remain available.",
        (true, false) => "Live answers are unavailable. Text remains available for the local/static demonstration.",
        _ => "Microphone and live answers are unavailable. Text remains available for the local/static demonstration.",
    };

    public string IntentDescription => Intent switch
    {
        CompanionIntent.Explain => "Explain the selected source with progressive detail.",
        CompanionIntent.Show => "Show an inert visual guide over the selected source.",
        CompanionIntent.Teach => "Teach the concept, then offer a safe practice step.",
        CompanionIntent.Assess => "Check understanding without exposing hidden answers.",
        _ => "Collaborate through the existing bounded task and approval path.",
    };

    public IReadOnlyDictionary<string, string> AccessibleControls { get; } =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["Question"] = "Question or learning request",
            ["ChooseSource"] = "Choose one window or display to share",
            ["StopSharing"] = "Stop sharing the selected source",
            ["StopSpeech"] = "Stop assistant speech",
            ["CancelTask"] = "Cancel the current Fleet task",
            ["StopAll"] = "Stop speech, sharing, and current task",
        };

    public void ConfigureCapabilities(bool microphoneAvailable, bool providerAvailable)
    {
        MicrophoneAvailable = microphoneAvailable;
        ProviderAvailable = providerAvailable;
        Raise(nameof(MicrophoneAvailable));
        Raise(nameof(ProviderAvailable));
        Raise(nameof(CapabilityMessage));
    }

    public void ConfigureAccessibility(double textScale, bool reducedMotion)
    {
        if (!double.IsFinite(textScale) || textScale is < 1.0 or > 2.0)
            throw new InvalidDataException("Text scale must be from 1.0 to 2.0.");
        TextScale = textScale;
        ReducedMotion = reducedMotion;
        Raise(nameof(TextScale));
        Raise(nameof(ReducedMotion));
    }

    public void SetIntent(CompanionIntent intent)
    {
        Intent = intent;
        Raise(nameof(Intent));
        Raise(nameof(IntentDescription));
    }

    public void SelectSource(string sourceId, string sourceRevision, string displayName)
    {
        RequireIdentifier(sourceId, nameof(sourceId));
        RequireIdentifier(sourceRevision, nameof(sourceRevision));
        if (string.IsNullOrWhiteSpace(displayName) || displayName.Length > 512)
            throw new InvalidDataException("Source display name is invalid.");
        if (_sourceId != sourceId || _sourceRevision != sourceRevision)
        {
            SourceEpoch++;
            _observationRevision = null;
            Raise(nameof(SourceEpoch));
            Raise(nameof(ObservationRevision));
        }
        _sourceId = sourceId;
        _sourceRevision = sourceRevision;
        _sourceDisplayName = displayName.Trim();
        SharingActive = true;
        RaiseSource();
    }

    public void BindObservation(string observationRevision)
    {
        if (!SharingActive || _sourceId is null)
            throw new InvalidOperationException("A selected source is required.");
        RequireIdentifier(observationRevision, nameof(observationRevision));
        _observationRevision = observationRevision;
        Raise(nameof(ObservationRevision));
    }

    public void StartSpeech()
    {
        if (!ProviderAvailable)
            throw new InvalidOperationException("Speech provider is unavailable.");
        SpeechPlaying = true;
        Raise(nameof(SpeechPlaying));
    }

    public void StopSpeech()
    {
        SpeechPlaying = false;
        SpeechEpoch++;
        Raise(nameof(SpeechPlaying));
        Raise(nameof(SpeechEpoch));
    }

    public void AttachTask(string taskId)
    {
        RequireIdentifier(taskId, nameof(taskId));
        _taskId = taskId;
        Raise(nameof(TaskId));
        Raise(nameof(TaskRunning));
    }

    public void CancelTask()
    {
        _taskId = null;
        Raise(nameof(TaskId));
        Raise(nameof(TaskRunning));
    }

    public void StopSharing()
    {
        _sourceId = null;
        _sourceRevision = null;
        _sourceDisplayName = null;
        _observationRevision = null;
        SharingActive = false;
        SourceEpoch++;
        RaiseSource();
        Raise(nameof(SourceEpoch));
        Raise(nameof(ObservationRevision));
    }

    public void ClosePanel()
    {
        PanelOpen = false;
        Raise(nameof(PanelOpen));
    }

    public void ReopenPanel()
    {
        PanelOpen = true;
        FocusTarget = "Question";
        Raise(nameof(PanelOpen));
        Raise(nameof(FocusTarget));
    }

    public void StopAll()
    {
        StopSpeech();
        StopSharing();
        CancelTask();
    }

    private void RaiseSource()
    {
        Raise(nameof(SourceId));
        Raise(nameof(SourceRevision));
        Raise(nameof(SourceDisplayName));
        Raise(nameof(SharingActive));
    }

    private void Set(ref string target, string value, [CallerMemberName] string name = "")
    {
        if (target == value) return;
        target = value;
        Raise(name);
    }

    private void Raise(string name) => PropertyChanged?.Invoke(this,
        new PropertyChangedEventArgs(name));

    private static void RequireIdentifier(string? value, string name)
    {
        if (value is null || !Identifier.IsMatch(value))
            throw new InvalidDataException($"{name} is invalid.");
    }
}
