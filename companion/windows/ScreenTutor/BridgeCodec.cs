using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace ScreenTutor;

/// <summary>Exact-byte authenticated typed bridge records; never an authority grant.</summary>
public static class BridgeCodec
{
    public const int MaxMessageBytes = 1024 * 1024;
    private static readonly string[] Fields = ["schema", "protocol_version", "session_id", "bridge_epoch",
        "sequence", "message_id", "reply_to", "deadline_monotonic_ms", "cancellation_generation", "message_type", "body"];
    private static readonly Regex Identifier = new("^[A-Za-z0-9_-]{1,128}$", RegexOptions.CultureInvariant);
    private static readonly Regex Digest = new("^[0-9a-f]{64}$", RegexOptions.CultureInvariant);
    private static readonly Dictionary<string, string[]> Bodies = new(StringComparer.Ordinal)
    {
        ["HELLO"] = ["peer", "challenge"],
        ["HELLO_ACK"] = ["peer", "challenge", "echo_challenge"],
        ["SELECT_SOURCE"] = ["source_id", "display_name", "source_kind", "source_revision", "native_handle_digest", "width", "height", "capture_epoch"],
        ["CAPTURE_AUTHORIZATION"] = ["schema", "session_id", "source_id", "source_revision", "capture_epoch", "consent_revision", "cancellation_generation", "now_monotonic_ms", "expires_at_monotonic_ms", "grant_created"],
        ["ASK"] = ["request"], ["ANSWER"] = ["instruction"],
        ["OBSERVATION"] = ["observation", "frame_reference"],
        ["FRAME"] = ["frame_reference"], ["FRAME_ACCEPTED"] = ["observation"],
        ["QUESTION"] = ["request_id", "observation_id", "question", "learning_intent", "locale"],
        ["PRESENTATION_RETIRED"] = ["binding", "reason_code"],
        ["PAUSE"] = ["reason_code"], ["STOP"] = ["reason_code"],
        ["UNAVAILABLE"] = ["reason_code", "detail"], ["REFUSAL"] = ["reason_code", "detail"]
        ,["PRACTICE_REQUEST"] = ["schema", "operation", "payload"]
        ,["PRACTICE_RESULT"] = ["schema", "state", "attempt_id", "artifact_count", "predicate_correct", "passing", "independent_success", "projection_status", "qualification"]
    };
    private static readonly Dictionary<string, string[]> Lessons = new(StringComparer.Ordinal)
    {
        ["request"] = ["schema", "request_id", "session_id", "user_id", "tenant_id", "project_id", "mode", "learning_intent", "question", "observation_ids", "source_ids", "skill_ids", "consent_revision", "cancellation_generation", "budget_reservation_id", "retention_policy_id", "deadline_monotonic_ms", "research_scope", "output_preferences"],
        ["instruction"] = ["schema", "request_id", "move", "answer", "claims", "annotations", "requested_response", "reveal_level", "expected_progress", "execution_request"],
        ["observation"] = ["schema", "observation_id", "session_id", "capture_epoch", "source_id", "source_kind", "source_revision", "user_id", "tenant_id", "project_id", "consent_revision", "captured_at_utc", "captured_at_monotonic_ms", "expires_at_monotonic_ms", "geometry_revision", "geometry", "modalities", "media", "artifact_ref", "content_sha256", "retention_policy_id"]
    };

    public static byte[] Encode(byte[] key, JsonElement envelope)
    {
        try
        {
            CheckKey(key);
            Shape(envelope, false);
            using var stream = new MemoryStream();
            using (var writer = new Utf8JsonWriter(stream)) WriteSorted(writer, envelope);
            var unsigned = stream.ToArray();
            var mac = Convert.ToHexString(HMACSHA256.HashData(key, unsigned)).ToLowerInvariant();
            var trailer = Encoding.ASCII.GetBytes(",\"mac\":\"" + mac + "\"}");
            if (unsigned.Length - 1 + trailer.Length > MaxMessageBytes)
                throw new InvalidDataException("Bridge message exceeds limit.");
            return unsigned[..^1].Concat(trailer).ToArray();
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException or FormatException or OverflowException)
        { throw new InvalidDataException("Invalid bridge message.", error); }
    }

    public static JsonDocument Decode(byte[] key, byte[] raw, string sessionId, long epoch,
        long sequence, long cancellationGeneration, long nowMs)
    {
        JsonDocument? document = null;
        try
        {
            CheckKey(key);
            if (raw.Length <= 74 || raw.Length > MaxMessageBytes || nowMs < 0)
                throw new InvalidDataException("Invalid bridge length or clock.");
            var trailer = Encoding.ASCII.GetString(raw[^74..]);
            if (!trailer.StartsWith(",\"mac\":\"", StringComparison.Ordinal)
                || !trailer.EndsWith("\"}", StringComparison.Ordinal)
                || !Digest.IsMatch(trailer.Substring(8, 64)))
                throw new InvalidDataException("Missing final bridge MAC.");
            var unsigned = raw[..^74].Concat(new byte[] { (byte)'}' }).ToArray();
            var computed = HMACSHA256.HashData(key, unsigned);
            var supplied = Convert.FromHexString(trailer.Substring(8, 64));
            if (!CryptographicOperations.FixedTimeEquals(computed, supplied))
                throw new InvalidDataException("Bridge authentication failed.");
            document = JsonDocument.Parse(raw, new JsonDocumentOptions { MaxDepth = 32 });
            var root = document.RootElement;
            Shape(root, true);
            if (root.GetProperty("session_id").GetString() != sessionId
                || root.GetProperty("bridge_epoch").GetInt64() != epoch
                || root.GetProperty("sequence").GetInt64() != sequence
                || root.GetProperty("cancellation_generation").GetInt64() != cancellationGeneration
                || root.GetProperty("deadline_monotonic_ms").GetInt64() <= nowMs)
                throw new InvalidDataException("Stale or foreign bridge message.");
            return document;
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException or FormatException or OverflowException or InvalidDataException)
        {
            document?.Dispose();
            throw new InvalidDataException("Bridge message refused.", error);
        }
    }

    private static void CheckKey(byte[] key)
    {
        if (key.Length < 32) throw new InvalidDataException("Bridge key requires at least 32 bytes.");
    }

    internal static void Closed(JsonElement value, IEnumerable<string> fields)
    {
        if (value.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Expected bridge object.");
        var actual = value.EnumerateObject().Select(p => p.Name).ToArray();
        if (actual.Distinct(StringComparer.Ordinal).Count() != actual.Length
            || !actual.ToHashSet(StringComparer.Ordinal).SetEquals(fields))
            throw new InvalidDataException("Bridge fields do not match protocol.");
    }

    internal static void Text(JsonElement value, int max, bool identifier = false)
    {
        if (value.ValueKind != JsonValueKind.String || value.GetString() is not string text
            || text.Length == 0 || text.EnumerateRunes().Count() > max || (identifier && !Identifier.IsMatch(text)))
            throw new InvalidDataException("Invalid bridge text.");
    }

    internal static long Integer(JsonElement value, long minimum = 0)
    {
        if (value.ValueKind != JsonValueKind.Number || !value.TryGetInt64(out var result) || result < minimum)
            throw new InvalidDataException("Invalid bridge integer.");
        return result;
    }

    private static void Shape(JsonElement root, bool withMac)
    {
        RejectDuplicates(root, 1);
        Closed(root, withMac ? Fields.Append("mac") : Fields);
        if (root.GetProperty("schema").GetString() != "fleet.tutor.bridge.v1"
            || root.GetProperty("protocol_version").GetString() is not ("1.1" or "1.2"))
            throw new InvalidDataException("Unsupported bridge version.");
        Text(root.GetProperty("session_id"), 128, true);
        Text(root.GetProperty("message_id"), 128, true);
        if (root.GetProperty("reply_to").ValueKind != JsonValueKind.Null) Text(root.GetProperty("reply_to"), 128, true);
        foreach (var name in new[] { "bridge_epoch", "sequence", "deadline_monotonic_ms" }) Integer(root.GetProperty(name), 1);
        Integer(root.GetProperty("cancellation_generation"));
        var kind = root.GetProperty("message_type").GetString() ?? "";
        if (!Bodies.TryGetValue(kind, out var fields)) throw new InvalidDataException("Unknown bridge type.");
        var body = root.GetProperty("body");
        Closed(body, kind == "ANSWER" && body.TryGetProperty("presentation",out _) ? ["instruction","presentation"] : fields);
        if (kind is "PRACTICE_REQUEST" or "PRACTICE_RESULT")
        {
            if (root.GetProperty("protocol_version").GetString() != "1.2") throw new InvalidDataException("Practice requires bridge1.2.");
            if (kind == "PRACTICE_REQUEST")
            {
                if (body.GetProperty("schema").GetString() != "fleet.tutor.practice-request.v1") throw new InvalidDataException("Invalid practice schema.");
                var operation = body.GetProperty("operation").GetString();
                if (operation is not ("STATUS" or "START" or "UPLOAD" or "SUBMIT" or "CANCEL")) throw new InvalidDataException("Unknown practice operation.");
                var payload=body.GetProperty("payload");
                Closed(payload, operation == "UPLOAD" ? ["artifact_base64"] : []);
                if (operation == "UPLOAD")
                {
                    Text(payload.GetProperty("artifact_base64"),349528);
                    var encoded=payload.GetProperty("artifact_base64").GetString()!;
                    byte[] raw;
                    try { raw=Convert.FromBase64String(encoded); }
                    catch(FormatException error) { throw new InvalidDataException("Invalid artifact encoding.",error); }
                    if (raw.Length is <1 or >262144 || Convert.ToBase64String(raw)!=encoded) throw new InvalidDataException("Invalid or oversized artifact.");
                }
            }
            else
            {
                if (body.GetProperty("schema").GetString() != "fleet.tutor.practice-result.v1"
                    || body.GetProperty("state").GetString() is not ("ASSIGNED" or "ACTIVE" or "SUBMITTED" or "CANCELLED")) throw new InvalidDataException("Invalid practice result.");
                if (body.GetProperty("attempt_id").ValueKind != JsonValueKind.Null) Text(body.GetProperty("attempt_id"),128,true);
                if (Integer(body.GetProperty("artifact_count"))>8) throw new InvalidDataException("Artifact count outside bounds.");
                foreach(var name in new[]{"predicate_correct","passing"})
                    if (body.GetProperty(name).ValueKind is not (JsonValueKind.True or JsonValueKind.False or JsonValueKind.Null)) throw new InvalidDataException("Invalid practice predicate.");
                if (body.GetProperty("independent_success").ValueKind is not (JsonValueKind.True or JsonValueKind.False)
                    || body.GetProperty("projection_status").GetString() is not ("UNASSESSED" or "CURRENT" or "STALE_EXPOSURE" or "UNAVAILABLE")
                    || body.GetProperty("qualification").GetString() is not ("UNASSESSED" or "LOCAL_ONLY" or "REVIEWED_PACK")) throw new InvalidDataException("Invalid practice qualification.");
            }
        }
        if (kind == "QUESTION")
        {
            Text(body.GetProperty("request_id"), 128, true); Text(body.GetProperty("observation_id"), 128, true);
            Text(body.GetProperty("question"), 8192); Text(body.GetProperty("locale"), 32);
            if (string.IsNullOrWhiteSpace(body.GetProperty("question").GetString())
                || body.GetProperty("learning_intent").GetString() is not ("UNDERSTAND" or "FINISH" or "LEARN" or "ASSESS"))
                throw new InvalidDataException("Invalid native question.");
        }
        if (kind is "HELLO" or "HELLO_ACK")
        {
            if (body.GetProperty("peer").GetString() is not ("HOST" or "NATIVE")) throw new InvalidDataException("Invalid peer.");
            foreach (var name in fields.Where(n => n != "peer"))
                if (body.GetProperty(name).GetString() is not string digest || !Digest.IsMatch(digest)) throw new InvalidDataException("Invalid challenge.");
        }
        if (kind == "PRESENTATION_RETIRED")
        {
            BridgePayloads.PresentationBinding(body.GetProperty("binding"));
            Text(body.GetProperty("reason_code"),128,true);
            if(root.GetProperty("reply_to").ValueKind != JsonValueKind.Null)
                throw new InvalidDataException("Retirement must be unsolicited.");
        }
        if (kind is "PAUSE" or "STOP" or "UNAVAILABLE" or "REFUSAL")
        {
            Text(body.GetProperty("reason_code"), 128, true);
            if (body.TryGetProperty("detail", out var detail)) Text(detail, 4096);
        }
        if (kind == "SELECT_SOURCE")
        {
            Text(body.GetProperty("source_id"), 128, true); Text(body.GetProperty("source_revision"), 128, true);
            Text(body.GetProperty("display_name"), 512);
            if (body.GetProperty("source_kind").GetString() is not ("WINDOW" or "REGION" or "DISPLAY" or "SELECTED_SURFACE" or "BROWSER_TAB" or "DOCUMENT" or "MEDIA")) throw new InvalidDataException("Invalid source kind.");
            if (body.GetProperty("native_handle_digest").GetString() is not string digest || !Digest.IsMatch(digest)) throw new InvalidDataException("Invalid source digest.");
            var width = Integer(body.GetProperty("width"), 1); var height = Integer(body.GetProperty("height"), 1);
            if (width > 8192 || height > 8192 || width * height * 4 > 32 * 1024 * 1024) throw new InvalidDataException("Source dimensions outside limit.");
            Integer(body.GetProperty("capture_epoch"), 1);
        }
        if (kind == "CAPTURE_AUTHORIZATION")
        {
            if (body.GetProperty("schema").GetString() != "fleet.tutor.capture-authorization.v1"
                || body.GetProperty("grant_created").ValueKind != JsonValueKind.False)
                throw new InvalidDataException("Capture authorization cannot mint a grant.");
            foreach (var name in new[] { "session_id", "source_id", "source_revision", "consent_revision" }) Text(body.GetProperty(name), 128, true);
            Integer(body.GetProperty("capture_epoch"), 1); Integer(body.GetProperty("cancellation_generation"));
            var start = Integer(body.GetProperty("now_monotonic_ms"));
            var expiry = Integer(body.GetProperty("expires_at_monotonic_ms"), 1);
            if (expiry <= start || expiry - start > 900000) throw new InvalidDataException("Capture authorization lifetime outside limit.");
        }
        foreach (var name in new[] { "request", "instruction", "observation", "frame_reference" })
            if (body.TryGetProperty(name, out var nested) && nested.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Nested bridge record must be object.");
        foreach (var lesson in Lessons)
        {
            if (!body.TryGetProperty(lesson.Key, out var nested)) continue;
            Closed(nested, lesson.Value);
            if (nested.GetProperty("schema").GetString() != "fleet.tutor." + lesson.Key + ".v1") throw new InvalidDataException("Invalid nested lesson schema.");
            BridgePayloads.Lesson(lesson.Key, nested);
        }
        if (body.TryGetProperty("presentation",out var presentation))
            BridgePayloads.Presentation(presentation,body.GetProperty("instruction").GetProperty("request_id").GetString()!,Integer(root.GetProperty("deadline_monotonic_ms"),1));
        if (kind == "OBSERVATION") BridgePayloads.Frame(body.GetProperty("frame_reference"), body.GetProperty("observation"));
        if (kind == "FRAME") BridgePayloads.Frame(body.GetProperty("frame_reference"));
    }

    private static void RejectDuplicates(JsonElement value, int depth)
    {
        if (depth > 32) throw new InvalidDataException("Bridge nesting exceeds limit.");
        if (value.ValueKind == JsonValueKind.Number)
        {
            var raw = value.GetRawText();
            var isInteger = !raw.Contains('.') && !raw.Contains('e') && !raw.Contains('E');
            if ((isInteger && !value.TryGetInt64(out _)) || !value.TryGetDouble(out var number) || !double.IsFinite(number))
                throw new InvalidDataException("Bridge numeric value outside supported range.");
        }
        if (value.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var property in value.EnumerateObject())
            {
                if (!names.Add(property.Name)) throw new InvalidDataException("Duplicate JSON property.");
                RejectDuplicates(property.Value, depth + 1);
            }
        }
        else if (value.ValueKind == JsonValueKind.Array)
            foreach (var item in value.EnumerateArray()) RejectDuplicates(item, depth + 1);
    }

    private static void WriteSorted(Utf8JsonWriter writer, JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Object)
        {
            writer.WriteStartObject();
            foreach (var property in value.EnumerateObject().OrderBy(p => p.Name, StringComparer.Ordinal))
            { writer.WritePropertyName(property.Name); WriteSorted(writer, property.Value); }
            writer.WriteEndObject();
        }
        else if (value.ValueKind == JsonValueKind.Array)
        {
            writer.WriteStartArray(); foreach (var item in value.EnumerateArray()) WriteSorted(writer, item); writer.WriteEndArray();
        }
        else value.WriteTo(writer);
    }
}
