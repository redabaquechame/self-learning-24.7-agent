using System.Runtime.InteropServices;

namespace ScreenTutor;

public sealed class GlobalShortcut : IDisposable
{
    public const int HotkeyId = 0x5343;
    private nint _window;
    public bool IsRegistered { get; private set; }
    public string? ConflictReason { get; private set; }

    public bool TryRegister(nint window, uint modifiers, uint virtualKey)
    {
        Dispose();
        _window = window;
        IsRegistered = RegisterHotKey(window, HotkeyId, modifiers, virtualKey);
        ConflictReason = IsRegistered ? null : "That shortcut is already in use. Choose another shortcut; Screen Tutor will not replace it.";
        return IsRegistered;
    }

    public void Dispose()
    {
        if (IsRegistered) UnregisterHotKey(_window, HotkeyId);
        IsRegistered = false;
        _window = 0;
        GC.SuppressFinalize(this);
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool RegisterHotKey(nint hWnd, int id, uint fsModifiers, uint vk);
    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UnregisterHotKey(nint hWnd, int id);
}
