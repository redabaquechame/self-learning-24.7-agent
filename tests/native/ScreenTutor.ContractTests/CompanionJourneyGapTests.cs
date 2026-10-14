using System.Windows;
using System.Windows.Automation.Peers;
using System.Windows.Controls;
using System.Windows.Threading;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Interop;
using System.Runtime.InteropServices;
using ScreenTutor;
using Button = System.Windows.Controls.Button;
using TextBox = System.Windows.Controls.TextBox;
using Point = System.Windows.Point;

internal static class CompanionJourneyGapTests
{
    internal static void OnboardingActions() => InOwnedWindow(window =>
    {
        var journey = (Onboarding)window.FindName("OnboardingJourney");
        window.Hide();
        Click((Button)journey.FindName("SummonStep"));
        Require(window.IsVisible && journey.CurrentStep == 1,
            "checklist summon claimed completion without showing the actual companion");
        var select = (Button)window.FindName("SelectButton");
        select.IsEnabled = false; // An already-active picker must not be started again; no OS/private picker in this witness.
        Click((Button)journey.FindName("SelectStep"));
        Require(journey.CurrentStep == 1 && !journey.Complete,
            "busy checklist source action claimed selection without a current authorized source");
        Click((Button)journey.FindName("AskStep"));
        Require(journey.CurrentStep == 1 && ((TextBlock)window.FindName("AnswerText")).Text == "",
            "unready checklist Ask manufactured an answer or completion");
        Click((Button)journey.FindName("ShowStep"));
        Require(journey.CurrentStep == 1 && !journey.Complete,
            "unavailable checklist visual guide manufactured completion");
        Click((Button)window.FindName("StopButton"));
        Require(!journey.Complete && journey.CurrentStep <= 1,
            "Stop manufactured the unfinished source/answer/guide stages");
        Console.WriteLine("[actual onboarding actions] summon shows real panel; busy/unready/unavailable actions and early Stop cannot self-certify completion");
    });

    internal static void UnsupportedControls() => InOwnedWindow(window =>
    {
        var help = FrameworkElementAutomationPeer.CreatePeerForElement((Button)window.FindName("CancelTaskButton"))?.GetHelpText();
        Require(help?.Contains("Fleet", StringComparison.OrdinalIgnoreCase) == true,
            "unavailable task control does not explain its actual recovery through accessible help");
        var speechHelp = FrameworkElementAutomationPeer.CreatePeerForElement((Button)window.FindName("StopSpeechButton"))?.GetHelpText();
        Require(speechHelp?.Contains("not connected", StringComparison.OrdinalIgnoreCase) == true,
            "unavailable speech control lacks accessible availability help");
        var session = (SessionViewModel)window.DataContext;
        session.AttachTask("owned-unrelated-task");
        ((TextBox)window.FindName("Question")).Text = "Retained owned control draft";
        var beforeSource = session.SourceEpoch;
        Click((Button)window.FindName("CancelTaskButton"));
        Require(session.TaskId == "owned-unrelated-task" && session.TaskRunning
                && !((TextBlock)window.FindName("Status")).Text.Contains("cancelled", StringComparison.OrdinalIgnoreCase),
            "unconnected task control erased the task reference or claimed a real cancellation");
        Click((Button)window.FindName("StopSpeechButton"));
        Require(!((TextBlock)window.FindName("Status")).Text.Contains("speech stopped", StringComparison.OrdinalIgnoreCase)
                && session.SourceEpoch == beforeSource && session.Draft == "Retained owned control draft",
            "unconnected speech control claimed playback Stop or changed sharing/draft");
        Console.WriteLine("[actual unavailable controls] absent task/speech integrations do not claim effects or erase unrelated task identity/draft/sharing");
    });

    internal static void MinimumLayout() => InOwnedWindow(window =>
    {
        window.Width = 380; window.Height = 440;
        var source = (TextBlock)window.FindName("SourceName");
        source.Text = "Owned source layout " + new string('W', 100);
        ((TextBlock)window.FindName("Status")).Text = string.Join(" ", Enumerable.Repeat("Owned long status remains readable.", 60));
        ((TextBlock)window.FindName("AnswerText")).Text = string.Join(" ", Enumerable.Repeat("Owned explanation layout sample.", 30));
        ((TextBlock)window.FindName("AnswerEvidence")).Text = string.Join(" ", Enumerable.Repeat("Owned evidence layout sample.", 30));
        var ask = (Button)window.FindName("AskButton");
        ask.IsEnabled = true; // Layout-only availability; focus/navigation never invokes this button or any provider.
        var journey = (Onboarding)window.FindName("OnboardingJourney");
        ((Expander)journey.Parent).IsExpanded = true;
        foreach (var fontSize in new[] { 12d, 18d })
        {
            window.FontSize = fontSize; window.UpdateLayout();
            FrameworkElement root = window;
            var stop = (Button)window.FindName("StopButton");
            var sourceBounds = Bounds(source, root); var stopBounds = Bounds(stop, root);
            Require(GetClientRect(new WindowInteropHelper(window).Handle, out var physicalClient), "owned window client bounds unavailable");
            var transform = HwndSource.FromHwnd(new WindowInteropHelper(window).Handle).CompositionTarget.TransformFromDevice;
            var clientSize = transform.Transform(new Point(physicalClient.Right, physicalClient.Bottom));
            var client = new Rect(0, 0, clientSize.X, clientSize.Y);
            Console.WriteLine($"[owned layout measurement] font={fontSize}, client={client}, source={sourceBounds}, stop={stopBounds}");
            Require(stopBounds.Width > 0 && stopBounds.Height > 0 && Contains(client, stopBounds)
                    && sourceBounds.Height > 0 && Contains(client, sourceBounds),
                "expanded onboarding/long source clipped source or Stop at minimum window size");
            var scroll = window.FindName("SessionContent") as ScrollViewer;
            Require(scroll is { ActualHeight: > 0 }, "minimum window has no usable question/answer scroll viewport");
            foreach (var name in new[] { "Question", "AskButton", "AnswerText", "AnswerEvidence", "Status", "StopSpeechButton", "CancelTaskButton" })
            {
                var element = (FrameworkElement)window.FindName(name);
                if (element is TextBlock { Text.Length: 0 }) continue;
                element.BringIntoView();
                if (element.Focusable && element.IsEnabled) Require(element.Focus(), name + " cannot receive keyboard focus");
                window.Dispatcher.Invoke(() => { }, DispatcherPriority.ApplicationIdle);
                window.UpdateLayout();
                var visible = VisibleBounds(element, window, client);
                Require(visible.Width > 0 && visible.Height > 0, name + " cannot be reached by scrolling/focus");
                Require(Contains(client, Bounds(stop, root)), "scrolling the content hid Stop sharing");
            }
            var peer = FrameworkElementAutomationPeer.CreatePeerForElement(source);
            Require(peer?.GetName() == source.Text, "bounded visible source title lost its full accessible identity");
            ((Button)window.FindName("SelectButton")).Focus();
            var visited = new HashSet<string>();
            for (var index = 0; index < 40; index++)
            {
                if (Keyboard.FocusedElement is not FrameworkElement focused) break;
                visited.Add(focused.Name);
                if (focused.Name is "Question" or "AskButton")
                    Require(!VisibleBounds(focused, window, client).IsEmpty, "WPF keyboard traversal left " + focused.Name + " outside its viewport");
                if (!focused.MoveFocus(new TraversalRequest(FocusNavigationDirection.Next))) break;
                window.Dispatcher.Invoke(() => { }, DispatcherPriority.ApplicationIdle);
            }
            Require(new[] { "SelectButton", "Question", "AskButton", "ExitButton" }.All(visited.Contains),
                "WPF keyboard navigation cannot reach the source, composer, enabled Ask and Exit");
            var question = (TextBox)window.FindName("Question");
            question.Text = "Retained draft after scrolling";
            scroll!.ScrollToEnd(); window.UpdateLayout();
            window.Close(); window.SummonPanel();
            window.Dispatcher.Invoke(() => { }, DispatcherPriority.ApplicationIdle);
            Require(window.IsVisible && question.IsKeyboardFocused && question.Text == "Retained draft after scrolling"
                    && !VisibleBounds(question, window, client).IsEmpty,
                "close/summon after scrolling lost visible keyboard focus or draft");
        }
        Console.WriteLine("[actual minimum layout] 380x440, expanded onboarding, long source/status and18-point text retain visible source/Stop and reachable content");
    });

    private static Rect Bounds(FrameworkElement child, FrameworkElement root)
        => child.TransformToAncestor(root).TransformBounds(new Rect(new Point(0, 0), child.RenderSize));
    private static Rect VisibleBounds(FrameworkElement child, Window window, Rect client)
    {
        var visible = Rect.Intersect(Bounds(child, window), client);
        for (var parent = VisualTreeHelper.GetParent(child); parent is not null && parent != window; parent = VisualTreeHelper.GetParent(parent))
            if (parent is FrameworkElement element && (element is ScrollViewer or ScrollContentPresenter || element.ClipToBounds))
                visible.Intersect(Bounds(element, window));
        return visible;
    }
    private static bool Contains(Rect outer, Rect inner)
        => inner.Left >= outer.Left - 1 && inner.Top >= outer.Top - 1
            && inner.Right <= outer.Right + 1 && inner.Bottom <= outer.Bottom + 1;
    private static void Click(Button button) => button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
    private static void Require(bool condition, string message)
    { if (!condition) throw new InvalidOperationException(message); }
    private static void InOwnedWindow(Action<SessionWindow> action)
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            SessionWindow? window = null;
            try { window = new SessionWindow(); window.Show(); window.UpdateLayout(); action(window); }
            catch (Exception error) { failure = error; }
            finally { window?.ExitCompanion(); Dispatcher.CurrentDispatcher.InvokeShutdown(); }
        });
        thread.SetApartmentState(ApartmentState.STA); thread.Start();
        Require(thread.Join(TimeSpan.FromSeconds(10)), "owned companion witness exceeded its bound");
        if (failure is not null) throw failure;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct ClientRectangle { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetClientRect(nint window, out ClientRectangle rectangle);
}
