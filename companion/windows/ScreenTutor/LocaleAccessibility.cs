using System.IO;
using System.Text.RegularExpressions;

namespace ScreenTutor;

public enum TerminologyUncertainty
{
    Known,
    Ambiguous,
    Untranslated
}

public sealed record TerminologyEntry(
    string TermId,
    string SourceTerm,
    string SourceLanguage,
    string? PreferredTerm,
    string TargetLanguage,
    TerminologyUncertainty Uncertainty,
    IReadOnlyList<string> SourceReferences);

public sealed class CandidateLocale
{
    private static readonly Regex LocalePattern = new(
        "^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-[A-Z]{2}|-[0-9]{3})?$",
        RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);

    public CandidateLocale(string localeId, string sourceLanguage,
        string targetLanguage, string fallbackLocale,
        IReadOnlyList<TerminologyEntry> glossary)
    {
        LocaleId = RequireLocale(localeId, nameof(localeId));
        SourceLanguage = RequireLocale(sourceLanguage, nameof(sourceLanguage));
        TargetLanguage = RequireLocale(targetLanguage, nameof(targetLanguage));
        FallbackLocale = RequireLocale(fallbackLocale, nameof(fallbackLocale));
        if (glossary.Count > 512 || glossary.Select(term => term.TermId).Distinct(
                StringComparer.Ordinal).Count() != glossary.Count)
            throw new InvalidDataException("candidate glossary is invalid");
        foreach (var term in glossary)
        {
            if (string.IsNullOrWhiteSpace(term.TermId)
                || string.IsNullOrWhiteSpace(term.SourceTerm)
                || term.SourceReferences.Count == 0
                || (term.Uncertainty == TerminologyUncertainty.Untranslated
                    && term.PreferredTerm is not null))
                throw new InvalidDataException("candidate terminology is invalid");
            RequireLocale(term.SourceLanguage, nameof(term.SourceLanguage));
            RequireLocale(term.TargetLanguage, nameof(term.TargetLanguage));
        }
        Glossary = glossary.ToArray();
    }

    public string LocaleId { get; }
    public string SourceLanguage { get; }
    public string TargetLanguage { get; }
    public string FallbackLocale { get; }
    public IReadOnlyList<TerminologyEntry> Glossary { get; }
    public bool Qualified => false;
    public string EffectiveLocale => FallbackLocale;
    public string Disclosure =>
        $"{LocaleId} is not yet qualified. Using visible text fallback in {FallbackLocale}.";

    private static string RequireLocale(string value, string name)
    {
        if (!LocalePattern.IsMatch(value))
            throw new InvalidDataException($"invalid {name}");
        return value;
    }
}

public sealed record CaptionLanguageSegment(int Start, int End, string Language);
public sealed record CaptionCorrection(
    string CorrectionId, int Revision, string CorrectedText, string Reason, string Actor);

public sealed class CaptionRecord
{
    private readonly List<CaptionCorrection> corrections = [];

    public CaptionRecord(string captionId, string origin, string rawText,
        string rawLanguage, IReadOnlyList<CaptionLanguageSegment> languageSegments)
    {
        if (string.IsNullOrWhiteSpace(captionId) || rawText.Length is < 1 or > 8000)
            throw new InvalidDataException("invalid caption identity or raw text");
        if (origin is not ("MICROPHONE" or "MEDIA" or "ASSISTANT"))
            throw new InvalidDataException("invalid caption origin");
        var cursor = 0;
        foreach (var segment in languageSegments)
        {
            if (segment.Start != cursor || segment.End <= segment.Start
                || segment.End > rawText.Length || string.IsNullOrWhiteSpace(segment.Language))
                throw new InvalidDataException("caption language spans must cover raw text in order");
            cursor = segment.End;
        }
        if (languageSegments.Count == 0 || cursor != rawText.Length)
            throw new InvalidDataException("caption language spans do not cover raw text");
        CaptionId = captionId;
        Origin = origin;
        RawText = rawText;
        RawLanguage = rawLanguage;
        LanguageSegments = languageSegments.ToArray();
    }

    public string CaptionId { get; }
    public string Origin { get; }
    public string RawText { get; }
    public string RawLanguage { get; }
    public IReadOnlyList<CaptionLanguageSegment> LanguageSegments { get; }
    public IReadOnlyList<CaptionCorrection> Corrections => corrections.AsReadOnly();
    public string DisplayText => corrections.Count == 0
        ? RawText : corrections[^1].CorrectedText;

    public void AppendCorrection(string correctionId, string correctedText,
        string reason, string actor)
    {
        if (corrections.Count >= 16 || string.IsNullOrWhiteSpace(correctionId)
            || string.IsNullOrWhiteSpace(correctedText) || string.IsNullOrWhiteSpace(reason)
            || actor is not ("USER" or "SYSTEM")
            || corrections.Any(item => item.CorrectionId == correctionId))
            throw new InvalidDataException("invalid caption correction");
        corrections.Add(new CaptionCorrection(correctionId, corrections.Count + 1,
            correctedText, reason, actor));
    }
}

public sealed class AudioDeviceCaptureGuard
{
    public AudioDeviceCaptureGuard(string deviceId)
    {
        DeviceId = RequireDevice(deviceId);
    }

    public string DeviceId { get; private set; }
    public int Generation { get; private set; }
    public bool CapturePaused { get; private set; } = true;
    public bool CaptureAuthorized { get; private set; }
    public bool MayCapture => CaptureAuthorized && !CapturePaused;

    public void Authorize(string deviceId, int generation)
    {
        if (deviceId != DeviceId || generation != Generation)
            throw new InvalidOperationException("stale device authorization");
        CaptureAuthorized = true;
        CapturePaused = false;
    }

    public void ChangeDevice(string deviceId)
    {
        deviceId = RequireDevice(deviceId);
        if (deviceId != DeviceId)
        {
            DeviceId = deviceId;
            Generation++;
        }
        CaptureAuthorized = false;
        CapturePaused = true;
    }

    private static string RequireDevice(string value)
    {
        if (string.IsNullOrWhiteSpace(value) || value.Length > 128)
            throw new InvalidDataException("invalid device identity");
        return value;
    }
}

public static class AudioAccessibility
{
    public const double MinimumSpeechRate = 0.5;
    public const double MaximumSpeechRate = 2.0;

    public static IReadOnlyDictionary<string, string> KeyboardEquivalents { get; } =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["PUSH_TO_TALK"] = "Space (hold)",
            ["BARGE_IN"] = "Escape",
            ["STOP_SPEECH"] = "Ctrl+Shift+S",
            ["FOCUS_TEXT_FALLBACK"] = "Ctrl+Shift+Q",
        };

    public static double ValidateSpeechRate(double value)
    {
        if (!double.IsFinite(value) || value < MinimumSpeechRate
            || value > MaximumSpeechRate)
            throw new ArgumentOutOfRangeException(nameof(value),
                "speech rate must be between 0.5 and 2.0");
        return value;
    }
}
