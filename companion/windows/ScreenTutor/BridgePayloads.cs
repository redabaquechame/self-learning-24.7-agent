using System.IO;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace ScreenTutor;

/// <summary>Structural record rules only. Live policy, target and memory admission remain host-owned.</summary>
internal static class BridgePayloads
{
    internal static void Presentation(JsonElement value, string requestId, long deadlineMs)
    {
        BridgeCodec.Closed(value,["schema","binding","expires_at_monotonic_ms","qualification","render_model","learning_success_claimed"]);
        if (value.GetProperty("schema").GetString() != "fleet.tutor.presentation.v1"
            || value.GetProperty("learning_success_claimed").ValueKind != JsonValueKind.False)
            throw new InvalidDataException("Invalid teaching presentation schema or learning flag.");
        Enum(value.GetProperty("qualification"),"LOCAL_ONLY","REVIEWED_PACK");
        var binding=value.GetProperty("binding");
        PresentationBinding(binding);
        if (binding.GetProperty("request_id").GetString()!=requestId || Number(value,"expires_at_monotonic_ms",1)>deadlineMs)
            throw new InvalidDataException("Teaching presentation exceeds answer request binding.");
        if (JsonSerializer.SerializeToUtf8Bytes(value).Length>256*1024)
            throw new InvalidDataException("Teaching presentation exceeds byte bound.");
        TeachingCanvas.ValidateRenderModel(JsonSerializer.SerializeToUtf8Bytes(value.GetProperty("render_model")));
    }

    internal static void PresentationBinding(JsonElement binding)
    {
        BridgeCodec.Closed(binding,["request_id","session_id","user_id","tenant_id","project_id","observation_id","source_id","source_revision","capture_epoch","geometry_revision","content_sha256","consent_revision","cancellation_generation"]);
        Ids(binding,"request_id","session_id","user_id","tenant_id","project_id","observation_id","source_id","source_revision","geometry_revision","consent_revision");
        Number(binding,"capture_epoch",1); Number(binding,"cancellation_generation"); Digest(binding.GetProperty("content_sha256"));
    }

    private static void Ids(JsonElement value, params string[] names)
    { foreach (var name in names) BridgeCodec.Text(value.GetProperty(name), 128, true); }
    private static void Text(JsonElement value, string name, int limit) => BridgeCodec.Text(value.GetProperty(name), limit);
    private static void Enum(JsonElement value, params string[] choices)
    {
        if (value.ValueKind != JsonValueKind.String || !choices.Contains(value.GetString(), StringComparer.Ordinal))
            throw new InvalidDataException("Unsupported nested enum.");
    }
    private static void List(JsonElement value, int limit)
    {
        if (value.ValueKind != JsonValueKind.Array || value.GetArrayLength() > limit) throw new InvalidDataException("Nested list outside bounds.");
    }
    private static void IdList(JsonElement value, int limit = 64)
    {
        List(value, limit); var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var item in value.EnumerateArray())
        { BridgeCodec.Text(item, 128, true); if (!seen.Add(item.GetString()!)) throw new InvalidDataException("Duplicate nested reference."); }
    }
    private static void Digest(JsonElement value)
    {
        if (value.ValueKind != JsonValueKind.String || !Regex.IsMatch(value.GetString()!, "^[0-9a-f]{64}$")) throw new InvalidDataException("Invalid nested digest.");
    }
    private static long Number(JsonElement value, string name, long min = 0) => BridgeCodec.Integer(value.GetProperty(name), min);

    internal static void Lesson(string kind, JsonElement value)
    {
        if (kind == "request")
        {
            Ids(value, "request_id", "session_id", "user_id", "tenant_id", "project_id", "budget_reservation_id", "retention_policy_id", "consent_revision");
            Enum(value.GetProperty("mode"), "EXPLAIN", "GUIDE", "COLLABORATE", "DELEGATE");
            Enum(value.GetProperty("learning_intent"), "UNDERSTAND", "FINISH", "LEARN", "ASSESS");
            Text(value, "question", 8192); Number(value, "deadline_monotonic_ms", 1); Number(value, "cancellation_generation");
            Enum(value.GetProperty("research_scope"), "SOURCE_ONLY", "PERMITTED_RESEARCH");
            foreach (var name in new[] { "observation_ids", "source_ids", "skill_ids" }) IdList(value.GetProperty(name));
            var preferences = value.GetProperty("output_preferences");
            BridgeCodec.Closed(preferences, ["response_format", "speech", "locale"]);
            Enum(preferences.GetProperty("response_format"), "TEXT", "TEXT_AND_SCENE");
            if (preferences.GetProperty("speech").ValueKind is not (JsonValueKind.True or JsonValueKind.False)) throw new InvalidDataException("Speech preference must be boolean.");
            Text(preferences, "locale", 32);
        }
        else if (kind == "instruction")
        {
            Ids(value, "request_id"); Text(value, "move", 128); Text(value, "answer", 32768); Text(value, "requested_response", 2048);
            Enum(value.GetProperty("reveal_level"), "NONE", "HINT", "PARTIAL", "DIRECT");
            var progress = value.GetProperty("expected_progress"); BridgeCodec.Closed(progress, ["kind", "scope"]);
            Ids(progress, "kind"); Text(progress, "scope", 2048);
            var claims = value.GetProperty("claims"); List(claims, 128);
            foreach (var claim in claims.EnumerateArray())
            {
                BridgeCodec.Closed(claim, ["kind", "text", "evidence_refs", "uncertainty"]);
                Ids(claim, "kind"); Text(claim, "text", 4096); IdList(claim.GetProperty("evidence_refs"));
                var uncertainty = claim.GetProperty("uncertainty");
                if (uncertainty.ValueKind != JsonValueKind.Number || !uncertainty.TryGetDouble(out var n) || !double.IsFinite(n) || n < 0 || n > 1) throw new InvalidDataException("Invalid uncertainty.");
            }
            var annotations = value.GetProperty("annotations"); List(annotations, 128);
            foreach (var annotation in annotations.EnumerateArray())
            {
                BridgeCodec.Closed(annotation, ["primitive", "observation_id", "target_id", "label", "geometry_revision"]);
                Enum(annotation.GetProperty("primitive"), "RECT", "ARROW", "POINT", "LABEL");
                Ids(annotation, "observation_id", "target_id", "geometry_revision"); Text(annotation, "label", 512);
            }
            var action = value.GetProperty("execution_request");
            if (action.ValueKind != JsonValueKind.Null)
            { BridgeCodec.Closed(action, ["operation", "target_id", "justification"]); Ids(action, "operation", "target_id"); Text(action, "justification", 2048); }
        }
        else
        {
            Ids(value, "observation_id", "session_id", "source_id", "source_revision", "user_id", "tenant_id", "project_id", "consent_revision", "geometry_revision", "retention_policy_id");
            Enum(value.GetProperty("source_kind"), "WINDOW", "REGION", "DISPLAY", "SELECTED_SURFACE", "BROWSER_TAB", "DOCUMENT", "MEDIA");
            Number(value, "capture_epoch");
            if (Number(value, "expires_at_monotonic_ms") <= Number(value, "captured_at_monotonic_ms")) throw new InvalidDataException("Invalid observation lifetime.");
            Text(value, "captured_at_utc", 40);
            if (!Regex.IsMatch(value.GetProperty("captured_at_utc").GetString()!, @"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")) throw new InvalidDataException("Invalid observation timestamp.");
            Geometry(value.GetProperty("geometry"));
            var modalities = value.GetProperty("modalities"); IdList(modalities, 16);
            foreach (var modality in modalities.EnumerateArray()) Enum(modality, "pixels", "accessibility", "text", "audio", "video");
            if (value.GetProperty("media").ValueKind is not (JsonValueKind.Null or JsonValueKind.Object)) throw new InvalidDataException("Invalid inert media metadata.");
            Text(value, "artifact_ref", 512); Digest(value.GetProperty("content_sha256"));
        }
    }

    private static void Geometry(JsonElement geometry)
    {
        BridgeCodec.Closed(geometry, ["coordinate_space", "source_width", "source_height", "crop", "model_width", "model_height", "desktop_origin_x", "desktop_origin_y", "native_dpi_scale"]);
        Enum(geometry.GetProperty("coordinate_space"), "source_pixels");
        foreach (var field in new[] { "source_width", "source_height", "model_width", "model_height" }) Number(geometry, field, 1);
        var placement = new[] { "desktop_origin_x", "desktop_origin_y", "native_dpi_scale" };
        if (!placement.All(field => geometry.GetProperty(field).ValueKind == JsonValueKind.Null))
        {
            foreach (var field in new[] { "desktop_origin_x", "desktop_origin_y" })
                if (geometry.GetProperty(field).ValueKind != JsonValueKind.Number || !geometry.GetProperty(field).TryGetInt64(out _)) throw new InvalidDataException("Invalid desktop coordinate.");
            var scale = geometry.GetProperty("native_dpi_scale");
            if (scale.ValueKind != JsonValueKind.Number || !scale.TryGetDouble(out var n) || !double.IsFinite(n) || n <= 0) throw new InvalidDataException("Invalid DPI scale.");
        }
        var crop = geometry.GetProperty("crop"); BridgeCodec.Closed(crop, ["x", "y", "width", "height"]);
        var x = Number(crop, "x"); var y = Number(crop, "y"); var w = Number(crop, "width", 1); var h = Number(crop, "height", 1);
        if (x > Number(geometry, "source_width", 1) - w || y > Number(geometry, "source_height", 1) - h) throw new InvalidDataException("Crop outside source.");
    }

    internal static void Frame(JsonElement reference, JsonElement? observation = null)
    {
        BridgeCodec.Closed(reference, ["schema", "transfer_id", "frame_receipt"]);
        Enum(reference.GetProperty("schema"), "fleet.tutor.frame-reference.v1"); Ids(reference, "transfer_id");
        var receipt = reference.GetProperty("frame_receipt");
        BridgeCodec.Closed(receipt, ["frame_id", "source_id", "source_revision", "capture_epoch", "captured_at_monotonic_ms", "width", "height", "pixel_format", "size_bytes", "content_sha256"]);
        Ids(receipt, "frame_id", "source_id", "source_revision"); Number(receipt, "capture_epoch", 1); Number(receipt, "captured_at_monotonic_ms");
        var width = Number(receipt, "width", 1); var height = Number(receipt, "height", 1);
        if (width > 8192 || height > 8192 || width * height * 4 > 32 * 1024 * 1024) throw new InvalidDataException("Frame dimensions outside bound.");
        Enum(receipt.GetProperty("pixel_format"), "BGRA8", "BGRA8_PREMULTIPLIED");
        if (Number(receipt, "size_bytes", 1) != width * height * 4) throw new InvalidDataException("Invalid exact BGRA length.");
        Digest(receipt.GetProperty("content_sha256"));
        if (observation is null) return;
        var observed = observation.Value;
        foreach (var field in new[] { "source_id", "source_revision", "content_sha256" })
            if (receipt.GetProperty(field).GetString() != observed.GetProperty(field).GetString()) throw new InvalidDataException("Frame source binding mismatch.");
        foreach (var field in new[] { "capture_epoch", "captured_at_monotonic_ms" })
            if (Number(receipt, field) != Number(observed, field)) throw new InvalidDataException("Frame epoch/time mismatch.");
        if (width != Number(observed.GetProperty("geometry"), "source_width", 1) || height != Number(observed.GetProperty("geometry"), "source_height", 1)) throw new InvalidDataException("Frame geometry mismatch.");
    }
}
