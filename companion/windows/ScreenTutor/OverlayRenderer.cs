using System.IO;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace ScreenTutor;

public sealed record OverlayPrimitive(
    string Kind, string TargetId, string Label,
    IReadOnlyList<GroundingPoint> Points, string Color, double Stroke);

public sealed record OverlayBinding(
    string ObservationId, string SourceId, string SourceRevision,
    long CaptureEpoch, string GeometryRevision, string Mode);

public sealed record OverlayTicket(
    string TicketId, OverlayBinding Binding, long ExpiresAtMonotonicMilliseconds,
    IReadOnlyList<OverlayPrimitive> Primitives, bool HitTestVisible,
    IReadOnlyList<string> InputPrivileges);

public sealed class OverlayRenderer
{
    public const int MaxPrimitives = 16;
    public const long MaxLifetimeMilliseconds = 30_000;
    private static readonly HashSet<string> Kinds = ["RECT", "ARROW", "POINT", "LABEL"];
    private static readonly HashSet<string> Modes = ["EXPLAIN", "GUIDE"];
    private static readonly Regex Identifier = new(
        "^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", RegexOptions.CultureInvariant);
    private static readonly Regex Color = new(
        "^#[0-9A-Fa-f]{6}$", RegexOptions.CultureInvariant);

    public OverlayTicket Schedule(
        string ticketId, string targetId, OverlayBinding binding, GroundingGeometry geometry,
        IReadOnlyList<OverlayPrimitive> primitives,
        long nowMonotonicMilliseconds, long expiresAtMonotonicMilliseconds)
    {
        RequireIdentifier(ticketId, nameof(ticketId));
        RequireIdentifier(targetId, nameof(targetId));
        ValidateBinding(binding);
        _ = new CoordinateMap(geometry);
        if (primitives is null || primitives.Count is < 1 or > MaxPrimitives)
            throw new InvalidDataException("Overlay primitive count is outside the bound.");
        if (nowMonotonicMilliseconds < 0 || expiresAtMonotonicMilliseconds < 0
            || expiresAtMonotonicMilliseconds <= nowMonotonicMilliseconds
            || expiresAtMonotonicMilliseconds - nowMonotonicMilliseconds > MaxLifetimeMilliseconds)
            throw new InvalidDataException("Overlay expiry is invalid.");
        foreach (var primitive in primitives)
        {
            ValidatePrimitive(primitive, geometry);
            if (!StringComparer.Ordinal.Equals(primitive.TargetId, targetId))
                throw new InvalidDataException("Overlay primitive target does not match the scheduled target.");
        }
        return new OverlayTicket(ticketId, binding, expiresAtMonotonicMilliseconds,
            primitives.ToArray(), false, Array.Empty<string>());
    }

    public bool TryRender(
        OverlayTicket ticket, OverlayBinding current, long nowMonotonicMilliseconds,
        out IReadOnlyList<OverlayPrimitive> primitives, out string reason)
    {
        ArgumentNullException.ThrowIfNull(ticket);
        ValidateBinding(current);
        primitives = Array.Empty<OverlayPrimitive>();
        if (nowMonotonicMilliseconds >= ticket.ExpiresAtMonotonicMilliseconds)
        {
            reason = "OVERLAY_EXPIRED";
            return false;
        }
        if (ticket.Binding != current)
        {
            reason = "STALE_OVERLAY_BINDING";
            return false;
        }
        if (ticket.HitTestVisible || ticket.InputPrivileges.Count != 0)
        {
            reason = "OVERLAY_INPUT_DENIED";
            return false;
        }
        primitives = ticket.Primitives;
        reason = "CURRENT_BINDING";
        return true;
    }

    public static OverlayPrimitive ParsePrimitive(ReadOnlySpan<byte> json)
    {
        if (json.Length is < 2 or > 16_384)
            throw new InvalidDataException("Primitive JSON is outside the byte bound.");
        try
        {
            using var document = JsonDocument.Parse(json.ToArray(), new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 8,
            });
            var root = document.RootElement;
            RequireExactProperties(root, "kind", "target_id", "label", "points", "style");
            var kind = RequiredString(root, "kind", 16);
            var targetId = RequiredString(root, "target_id", 128);
            var label = RequiredString(root, "label", 256);
            var style = root.GetProperty("style");
            RequireExactProperties(style, "color", "stroke");
            var color = RequiredString(style, "color", 7);
            var stroke = style.GetProperty("stroke").GetDouble();
            var pointsElement = root.GetProperty("points");
            if (pointsElement.ValueKind != JsonValueKind.Array)
                throw new InvalidDataException("Primitive points must be an array.");
            var points = new List<GroundingPoint>();
            foreach (var point in pointsElement.EnumerateArray())
            {
                RequireExactProperties(point, "x", "y");
                points.Add(new GroundingPoint(
                    point.GetProperty("x").GetDouble(), point.GetProperty("y").GetDouble()));
            }
            var primitive = new OverlayPrimitive(kind, targetId, label, points, color, stroke);
            ValidatePrimitiveShape(primitive);
            return primitive;
        }
        catch (JsonException error)
        {
            throw new InvalidDataException("Primitive JSON is malformed.", error);
        }
        catch (InvalidOperationException error)
        {
            throw new InvalidDataException("Primitive JSON has an invalid value type.", error);
        }
    }

    private static void ValidateBinding(OverlayBinding binding)
    {
        ArgumentNullException.ThrowIfNull(binding);
        RequireIdentifier(binding.ObservationId, nameof(binding.ObservationId));
        RequireIdentifier(binding.SourceId, nameof(binding.SourceId));
        RequireIdentifier(binding.SourceRevision, nameof(binding.SourceRevision));
        RequireIdentifier(binding.GeometryRevision, nameof(binding.GeometryRevision));
        if (binding.CaptureEpoch < 0 || !Modes.Contains(binding.Mode))
            throw new InvalidDataException("Overlay binding has an invalid epoch or mode.");
    }

    private static void ValidatePrimitive(OverlayPrimitive primitive, GroundingGeometry geometry)
    {
        ArgumentNullException.ThrowIfNull(primitive);
        ValidatePrimitiveShape(primitive);
        var map = new CoordinateMap(geometry);
        foreach (var point in primitive.Points) _ = map.ModelToDesktopDip(point);
    }

    private static void ValidatePrimitiveShape(OverlayPrimitive primitive)
    {
        if (!Kinds.Contains(primitive.Kind))
            throw new InvalidDataException("Overlay primitive kind is not inert and approved.");
        RequireIdentifier(primitive.TargetId, nameof(primitive.TargetId));
        if (string.IsNullOrWhiteSpace(primitive.Label) || primitive.Label.Length > 256)
            throw new InvalidDataException("Overlay label is invalid.");
        if (!Color.IsMatch(primitive.Color) || !double.IsFinite(primitive.Stroke)
            || primitive.Stroke <= 0 || primitive.Stroke > 8)
            throw new InvalidDataException("Overlay style is invalid.");
        var expected = primitive.Kind is "POINT" or "LABEL" ? 1 : 2;
        if (primitive.Points.Count != expected
            || primitive.Points.Any(point => !double.IsFinite(point.X) || !double.IsFinite(point.Y)))
            throw new InvalidDataException("Overlay primitive point count or value is invalid.");
    }

    private static void RequireIdentifier(string value, string name)
    {
        if (string.IsNullOrEmpty(value) || !Identifier.IsMatch(value))
            throw new InvalidDataException($"Invalid {name}.");
    }

    private static string RequiredString(JsonElement element, string name, int maximum)
    {
        if (!element.TryGetProperty(name, out var property)
            || property.ValueKind != JsonValueKind.String)
            throw new InvalidDataException($"Primitive {name} is missing or not text.");
        var value = property.GetString() ?? "";
        if (string.IsNullOrWhiteSpace(value) || value.Length > maximum)
            throw new InvalidDataException($"Primitive {name} is invalid.");
        return value;
    }

    private static void RequireExactProperties(JsonElement element, params string[] expected)
    {
        if (element.ValueKind != JsonValueKind.Object)
            throw new InvalidDataException("Primitive value must be an object.");
        var wanted = expected.ToHashSet(StringComparer.Ordinal);
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in element.EnumerateObject())
            if (!seen.Add(property.Name) || !wanted.Contains(property.Name))
                throw new InvalidDataException("Primitive JSON contains duplicate or unknown fields.");
        if (!seen.SetEquals(wanted))
            throw new InvalidDataException("Primitive JSON is missing required fields.");
    }
}
