using System.Security.Cryptography;
using System.Text.Json;

var path = args.Length == 1 ? args[0] : "tutor-contracts.v1.json";
var bytes = File.ReadAllBytes(path);
using var document = JsonDocument.Parse(bytes, new JsonDocumentOptions {
    AllowTrailingCommas = false,
    CommentHandling = JsonCommentHandling.Disallow,
    MaxDepth = 32
});
var root = document.RootElement;
RequireString(root, "protocol", "1.1");
RequireString(root, "minimum_protocol", "1.0");
var records = RequireObject(root, "records");
var expected = new Dictionary<string, string> {
    ["grant_view"] = "fleet.tutor.session_grant_view.v1",
    ["observation"] = "fleet.tutor.observation.v1",
    ["request"] = "fleet.tutor.request.v1",
    ["instruction"] = "fleet.tutor.instruction.v1",
    ["evidence"] = "fleet.tutor.learner_evidence.v1"
};
foreach (var item in expected) {
    var record = RequireObject(records, item.Key);
    RequireString(record, "schema", item.Value);
}
var observation = RequireObject(records, "observation");
RequireInteger(observation, "capture_epoch");
RequireInteger(observation, "captured_at_monotonic_ms");
RequireInteger(observation, "expires_at_monotonic_ms");
RequireObject(observation, "geometry");
RequireArray(observation, "modalities");
var request = RequireObject(records, "request");
RequireString(request, "mode", "GUIDE");
RequireString(request, "learning_intent", "LEARN");
RequireInteger(request, "cancellation_generation");
RequireInteger(request, "deadline_monotonic_ms");
var instruction = RequireObject(records, "instruction");
if (instruction.GetProperty("execution_request").ValueKind != JsonValueKind.Null)
    throw new InvalidDataException("Guide fixture must not carry execution_request");
RequireArray(instruction, "claims");
RequireArray(instruction, "annotations");
Console.WriteLine($"PASS contract-probe sha256={Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant()}");

static JsonElement RequireObject(JsonElement parent, string name) {
    var value = parent.GetProperty(name);
    if (value.ValueKind != JsonValueKind.Object)
        throw new InvalidDataException($"{name} must be an object");
    return value;
}
static void RequireArray(JsonElement parent, string name) {
    if (parent.GetProperty(name).ValueKind != JsonValueKind.Array)
        throw new InvalidDataException($"{name} must be an array");
}
static void RequireInteger(JsonElement parent, string name) {
    if (!parent.GetProperty(name).TryGetInt64(out _))
        throw new InvalidDataException($"{name} must be an integer");
}
static void RequireString(JsonElement parent, string name, string expected) {
    if (parent.GetProperty(name).GetString() != expected)
        throw new InvalidDataException($"{name} must equal {expected}");
}
