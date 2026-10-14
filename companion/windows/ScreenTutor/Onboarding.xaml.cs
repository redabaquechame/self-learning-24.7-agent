using System.IO;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;

namespace ScreenTutor;

public partial class Onboarding : UserControl
{
    private static readonly string[] Steps = ["SUMMON", "SELECT", "ASK", "SHOW", "STOP"];
    private static readonly string[] Statuses =
    [
        "Companion open. Choose the window or display you want help with.",
        "Your source is authorized. Type a question and ask.",
        "Explanation displayed. Visual guidance is unavailable in this build. You can keep asking or stop sharing.",
        "Visual guide and practice complete. Stop sharing.",
        "Demonstration complete. Sharing and transient frames are stopped."
    ];

    public Onboarding()
    {
        InitializeComponent();
    }

    public int CurrentStep { get; private set; }
    public bool Complete => CurrentStep == Steps.Length;
    public string CurrentInstruction => JourneyStatus.Text;
    public string AccessibilityName => AutomationProperties.GetName(this);
    public event EventHandler<string>? ActionRequested;

    public bool TryCompleteStep(string step)
    {
        if (CurrentStep >= Steps.Length || step != Steps[CurrentStep]) return false;
        CompleteStep(step);
        return true;
    }

    public void InvalidateSourceProgress()
    {
        if (CurrentStep == 0) return;
        CurrentStep = 1;
        JourneyProgress.Value = CurrentStep;
        JourneyStatus.Text = "Choose and authorize your source to continue. You can stop sharing at any time.";
        UpdateButtons();
    }

    public void InvalidateAnswerProgress()
    {
        if (CurrentStep is < 3 or >= 5) return;
        CurrentStep = 2;
        JourneyProgress.Value = CurrentStep;
        JourneyStatus.Text = "Ask about the current view of your selected source.";
        UpdateButtons();
    }

    public void CompleteStep(string step)
    {
        if (CurrentStep >= Steps.Length)
            throw new InvalidOperationException("The demonstration is already complete.");
        if (!string.Equals(step, Steps[CurrentStep], StringComparison.Ordinal))
            throw new InvalidDataException($"Expected onboarding step {Steps[CurrentStep]}.");
        CurrentStep++;
        JourneyProgress.Value = CurrentStep;
        JourneyStatus.Text = Statuses[CurrentStep - 1];
        UpdateButtons();
    }

    public void ResetJourney()
    {
        CurrentStep = 0;
        JourneyProgress.Value = 0;
        JourneyStatus.Text = "Ready: summon the companion.";
        UpdateButtons();
    }

    public string ControlAccessibilityName(string step) => step switch
    {
        "SUMMON" => AutomationProperties.GetName(SummonStep),
        "SELECT" => AutomationProperties.GetName(SelectStep),
        "ASK" => AutomationProperties.GetName(AskStep),
        "SHOW" => AutomationProperties.GetName(ShowStep),
        "STOP" => AutomationProperties.GetName(StopStep),
        _ => throw new InvalidDataException("Unknown onboarding step."),
    };

    private void Step_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string step } && CurrentStep < Steps.Length && step == Steps[CurrentStep])
            ActionRequested?.Invoke(this, step);
    }

    private void UpdateButtons()
    {
        var buttons = new[] { SummonStep, SelectStep, AskStep, ShowStep, StopStep };
        for (var index = 0; index < buttons.Length; index++)
            buttons[index].IsEnabled = index == CurrentStep;
        ShowStep.IsEnabled = false; // No visible guide/circle integration yet; a click cannot certify one.
    }
}
