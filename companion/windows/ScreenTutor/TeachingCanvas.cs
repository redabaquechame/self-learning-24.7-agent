using System.IO;
using System.Text.Json;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Input;
using System.Windows.Media;

namespace ScreenTutor;

internal sealed record TeachingPrimitive(string Kind, string Id, JsonElement Payload);
internal sealed record TeachingScene(string SceneId, string TextAlternative,
    IReadOnlyList<TeachingPrimitive> Primitives);

/// <summary>
/// Renders the closed tutor.canvas-render/1 record. Practice ink lives only in
/// this control and has no source-document or application-input handle.
/// </summary>
public sealed class TeachingCanvas : FrameworkElement
{
    public const int MaxPrimitives = 64;
    public const int MaxInkStrokes = 512;
    public const int MaxPointsPerStroke = 2048;
    private static readonly Regex Identifier = new(
        "^[A-Za-z][A-Za-z0-9_-]{0,127}$", RegexOptions.CultureInvariant);
    private static readonly HashSet<string> Kinds =
        ["TEXT", "AXES", "EQUATION", "GRAPH", "NODE", "EDGE", "SLIDER"];
    private static readonly HashSet<string> Operations =
        ["ADD", "SUB", "MUL", "DIV", "POW", "MIN", "MAX"];
    private readonly List<IReadOnlyList<Point>> _ink = [];
    private List<Point>? _activeStroke;
    private TeachingScene? _scene;
    private bool _stopped;

    public string TextAlternative => _scene?.TextAlternative ?? string.Empty;
    public string? SourceDocumentSha256 { get; private set; }
    public int InkStrokeCount => _ink.Count;

    public TeachingCanvas()
    {
        Focusable = true;
        Cursor = Cursors.Pen;
        MouseLeftButtonDown += BeginStroke;
        MouseMove += ContinueStroke;
        MouseLeftButtonUp += EndStroke;
    }

    public void LoadRenderModel(ReadOnlyMemory<byte> payload)
    {
        if (_stopped) throw new InvalidOperationException("A stopped teaching canvas cannot load a scene.");
        _scene = null;
        _ink.Clear();
        InvalidateVisual();
        _scene = ParseRenderModel(payload);
        AutomationProperties.SetName(this, $"Teaching canvas: {_scene.SceneId}");
        AutomationProperties.SetHelpText(this, _scene.TextAlternative);
        InvalidateVisual();
    }

    public static void ValidateRenderModel(ReadOnlyMemory<byte> payload) => _ = ParseRenderModel(payload);

    private static TeachingScene ParseRenderModel(ReadOnlyMemory<byte> payload)
    {
        if (payload.Length is <= 0 or > 1024 * 1024)
            throw new InvalidDataException("Teaching scene bytes are outside bounds.");
        try
        {
            using var document = JsonDocument.Parse(payload,
                new JsonDocumentOptions { MaxDepth = 32 });
            var root = document.RootElement;
            RequireFields(root, "schema", "status", "scene_id", "primitives",
                "slider_values", "text_alternative", "executable_content");
            if (root.GetProperty("schema").GetString() != "tutor.canvas-render/1"
                || root.GetProperty("status").GetString() != "RENDER"
                || root.GetProperty("executable_content").ValueKind != JsonValueKind.False)
                throw new InvalidDataException("Teaching scene schema, status or executable flag is invalid.");
            var sceneId = RequiredIdentifier(root.GetProperty("scene_id"), "scene_id");
            var alternative = RequiredText(root.GetProperty("text_alternative"),
                "text_alternative", 4000);
            var sliderValues = root.GetProperty("slider_values");
            if (sliderValues.ValueKind != JsonValueKind.Object)
                throw new InvalidDataException("Slider values must be an object.");
            RejectDuplicateProperties(sliderValues);
            if (sliderValues.EnumerateObject().Count() > 16)
                throw new InvalidDataException("Slider values exceed bounds.");
            foreach (var property in sliderValues.EnumerateObject())
            {
                if (!Identifier.IsMatch(property.Name))
                    throw new InvalidDataException("Slider variable is invalid.");
                _ = RequiredNumber(property.Value, "slider value");
            }
            var primitiveArray = root.GetProperty("primitives");
            if (primitiveArray.ValueKind != JsonValueKind.Array
                || primitiveArray.GetArrayLength() is <= 0 or > MaxPrimitives)
                throw new InvalidDataException("Teaching primitive count is outside bounds.");
            var primitives = new List<TeachingPrimitive>();
            var ids = new HashSet<string>(StringComparer.Ordinal);
            foreach (var element in primitiveArray.EnumerateArray())
            {
                RequireFields(element, "kind", "id", "payload");
                var kind = RequiredText(element.GetProperty("kind"), "kind", 24);
                var id = RequiredIdentifier(element.GetProperty("id"), "id");
                if (!Kinds.Contains(kind) || !ids.Add(id))
                    throw new InvalidDataException("Teaching primitive kind or identity is invalid.");
                ValidatePayload(kind, element.GetProperty("payload"));
                primitives.Add(new TeachingPrimitive(kind, id,
                    element.GetProperty("payload").Clone()));
            }
            ValidateSceneRelations(primitives, sliderValues);
            return new TeachingScene(sceneId, alternative, primitives);
        }
        catch (InvalidDataException) { throw; }
        catch (Exception error) when (error is JsonException or InvalidOperationException
                                      or FormatException or OverflowException)
        {
            throw new InvalidDataException("Teaching scene JSON is malformed.", error);
        }
    }

    public void BeginPracticeInk(string sourceDocumentSha256)
    {
        if (_stopped) throw new InvalidOperationException("Teaching canvas is stopped.");
        if (sourceDocumentSha256.Length != 64
            || sourceDocumentSha256.Any(character => !Uri.IsHexDigit(character)))
            throw new InvalidDataException("Source document digest is invalid.");
        SourceDocumentSha256 = sourceDocumentSha256.ToLowerInvariant();
        _ink.Clear();
        InvalidateVisual();
    }

    internal void AddPracticeStroke(IReadOnlyList<Point> points)
    {
        if (_stopped || SourceDocumentSha256 is null)
            throw new InvalidOperationException("Practice ink is not active.");
        if (points.Count is <= 0 or > MaxPointsPerStroke || _ink.Count >= MaxInkStrokes)
            throw new InvalidDataException("Practice ink exceeds bounds.");
        if (points.Any(point => !double.IsFinite(point.X) || !double.IsFinite(point.Y)))
            throw new InvalidDataException("Practice ink point is invalid.");
        _ink.Add(points.ToArray());
        InvalidateVisual();
    }

    public void ResetPracticeInk()
    {
        if (_stopped) throw new InvalidOperationException("Teaching canvas is stopped.");
        _activeStroke = null;
        ReleaseMouseCapture();
        _ink.Clear();
        InvalidateVisual();
    }

    public void Stop()
    {
        _scene = null;
        AutomationProperties.SetHelpText(this, string.Empty);
        AutomationProperties.SetName(this, "Teaching canvas unavailable");
        _activeStroke = null;
        _ink.Clear();
        SourceDocumentSha256 = null;
        _stopped = true;
        ReleaseMouseCapture();
        InvalidateVisual();
    }

    protected override void OnRender(DrawingContext drawingContext)
    {
        base.OnRender(drawingContext);
        drawingContext.DrawRectangle(Brushes.White, null,
            new Rect(0, 0, Math.Max(0, ActualWidth), Math.Max(0, ActualHeight)));
        if (_stopped || _scene is null) return;
        var pen = new Pen(new SolidColorBrush(Color.FromRgb(35, 84, 130)), 2);
        var accent = new Pen(new SolidColorBrush(Color.FromRgb(15, 135, 110)), 3);
        var nodeBrush = new SolidColorBrush(Color.FromRgb(225, 241, 255));
        var typeface = new Typeface("Segoe UI");
        var nodes = new Dictionary<string, Point>(StringComparer.Ordinal);
        foreach (var primitive in _scene.Primitives.Where(item => item.Kind == "NODE"))
            nodes[primitive.Id] = UnitPoint(primitive.Payload);
        foreach (var primitive in _scene.Primitives)
        {
            var payload = primitive.Payload;
            if (primitive.Kind == "TEXT")
                DrawText(drawingContext, RequiredText(payload.GetProperty("text"), "text", 1000),
                    UnitPoint(payload), typeface, 18);
            else if (primitive.Kind == "AXES")
                DrawAxes(drawingContext, pen, typeface, payload);
            else if (primitive.Kind == "EQUATION")
                DrawText(drawingContext, RequiredText(payload.GetProperty("label"), "label", 500),
                    new Point(60, Math.Max(30, ActualHeight - 32)), typeface, 16, false);
            else if (primitive.Kind == "GRAPH")
                DrawGraph(drawingContext, accent, payload, _scene.Primitives.Single(item=>item.Kind=="AXES").Payload);
            else if (primitive.Kind == "NODE")
            {
                var point = UnitPoint(payload);
                drawingContext.DrawEllipse(nodeBrush, pen, point, 36, 24);
                DrawText(drawingContext, RequiredText(payload.GetProperty("label"), "label", 200),
                    new Point(point.X - 30, point.Y - 9), typeface, 12, false);
            }
            else if (primitive.Kind == "EDGE"
                     && nodes.TryGetValue(payload.GetProperty("from_id").GetString()!, out var from)
                     && nodes.TryGetValue(payload.GetProperty("to_id").GetString()!, out var to))
                drawingContext.DrawLine(pen, from, to);
            else if (primitive.Kind == "SLIDER")
            {
                var label = RequiredText(payload.GetProperty("label"), "label", 120);
                var value = RequiredNumber(payload.GetProperty("value"), "value");
                DrawText(drawingContext, $"{label}: {value:g}",
                    new Point(Math.Max(20, ActualWidth - 180), 22), typeface, 14, false);
            }
        }
        var inkPen = new Pen(new SolidColorBrush(Color.FromRgb(226, 91, 47)), 3);
        foreach (var stroke in _ink)
            for (var index = 1; index < stroke.Count; index++)
                drawingContext.DrawLine(inkPen, stroke[index - 1], stroke[index]);
    }

    private void BeginStroke(object sender, MouseButtonEventArgs args)
    {
        if (_stopped || SourceDocumentSha256 is null || _ink.Count >= MaxInkStrokes) return;
        _activeStroke = [args.GetPosition(this)];
        CaptureMouse();
        args.Handled = true;
    }

    private void ContinueStroke(object sender, MouseEventArgs args)
    {
        if (_activeStroke is null || args.LeftButton != MouseButtonState.Pressed
            || _activeStroke.Count >= MaxPointsPerStroke) return;
        _activeStroke.Add(args.GetPosition(this));
        InvalidateVisual();
    }

    private void EndStroke(object sender, MouseButtonEventArgs args)
    {
        if (_activeStroke is not null)
        {
            if (_activeStroke.Count < MaxPointsPerStroke)
                _activeStroke.Add(args.GetPosition(this));
            AddPracticeStroke(_activeStroke);
            _activeStroke = null;
        }
        ReleaseMouseCapture();
        args.Handled = true;
    }

    private Point UnitPoint(JsonElement payload) => new(
        RequiredNumber(payload.GetProperty("x"), "x") * Math.Max(1, ActualWidth),
        RequiredNumber(payload.GetProperty("y"), "y") * Math.Max(1, ActualHeight));

    private static void DrawText(DrawingContext context, string text, Point point,
        Typeface typeface, double size, bool unit = true)
    {
        context.DrawText(new FormattedText(text, System.Globalization.CultureInfo.InvariantCulture,
            FlowDirection.LeftToRight, typeface, size, Brushes.Black, 1.0), point);
    }

    private void DrawAxes(DrawingContext context, Pen pen, Typeface typeface, JsonElement payload)
    {
        var left = 60.0; var right = Math.Max(left + 1, ActualWidth - 40);
        var top = 42.0; var bottom = Math.Max(top + 1, ActualHeight - 70);
        context.DrawLine(pen, new Point(left, bottom), new Point(right, bottom));
        context.DrawLine(pen, new Point(left, bottom), new Point(left, top));
        DrawText(context, RequiredText(payload.GetProperty("x_label"), "x_label", 80),
            new Point(right - 8, bottom + 8), typeface, 12, false);
        DrawText(context, RequiredText(payload.GetProperty("y_label"), "y_label", 80),
            new Point(left - 22, top), typeface, 12, false);
    }

    private void DrawGraph(DrawingContext context, Pen pen, JsonElement payload, JsonElement axes)
    {
        var inputVariable = payload.GetProperty("input_variable").GetString()
            ?? throw new InvalidDataException("Graph input variable is missing.");
        var samples = payload.GetProperty("samples").EnumerateArray()
            .Select(sample => new Point(
                RequiredNumber(sample.GetProperty("inputs").GetProperty(inputVariable), "graph input"),
                RequiredNumber(sample.GetProperty("output"), "output"))).ToArray();
        var minX = RequiredNumber(axes.GetProperty("x_min"),"x_min"); var maxX = RequiredNumber(axes.GetProperty("x_max"),"x_max");
        var minY = RequiredNumber(axes.GetProperty("y_min"),"y_min"); var maxY = RequiredNumber(axes.GetProperty("y_max"),"y_max");
        var left=60.0;var right=Math.Max(left+1,ActualWidth-40);var top=42.0;var bottom=Math.Max(top+1,ActualHeight-70);
        Point Map(Point point) => new(
            left+(point.X-minX)/(maxX-minX)*(right-left),
            bottom-(point.Y-minY)/(maxY-minY)*(bottom-top));
        int Outside(Point p)=>(p.X<minX?1:p.X>maxX?2:0)|(p.Y<minY?4:p.Y>maxY?8:0);
        bool Clip(ref Point a,ref Point b)
        {
            for(var attempt=0;attempt<8;attempt++)
            {
                var ca=Outside(a);var cb=Outside(b);
                if((ca|cb)==0)return true;if((ca&cb)!=0)return false;
                var code=ca!=0?ca:cb;Point next;
                if((code&8)!=0)next=new Point(a.X+(b.X-a.X)*((maxY-a.Y)/(b.Y-a.Y)),maxY);
                else if((code&4)!=0)next=new Point(a.X+(b.X-a.X)*((minY-a.Y)/(b.Y-a.Y)),minY);
                else if((code&2)!=0)next=new Point(maxX,a.Y+(b.Y-a.Y)*((maxX-a.X)/(b.X-a.X)));
                else next=new Point(minX,a.Y+(b.Y-a.Y)*((minX-a.X)/(b.X-a.X)));
                if(ca!=0)a=next;else b=next;
            }
            return false;
        }
        context.PushClip(new RectangleGeometry(new Rect(left,top,right-left,bottom-top)));
        if(samples.Length==1 && Outside(samples[0])==0)context.DrawEllipse(pen.Brush,null,Map(samples[0]),2,2);
        for (var index = 1; index < samples.Length; index++)
        {
            var a=samples[index-1];var b=samples[index];
            if(Clip(ref a,ref b))context.DrawLine(pen,Map(a),Map(b));
        }
        context.Pop();
    }

    private static void ValidatePayload(string kind, JsonElement payload)
    {
        if (kind == "TEXT")
        {
            RequireFields(payload, "text", "x", "y");
            _ = RequiredText(payload.GetProperty("text"), "text", 1000);
            RequiredUnit(payload.GetProperty("x"), "x"); RequiredUnit(payload.GetProperty("y"), "y");
        }
        else if (kind == "AXES")
        {
            RequireFields(payload, "x_min", "x_max", "y_min", "y_max", "x_label", "y_label");
            var xMin = RequiredNumber(payload.GetProperty("x_min"), "x_min");
            var xMax = RequiredNumber(payload.GetProperty("x_max"), "x_max");
            var yMin = RequiredNumber(payload.GetProperty("y_min"), "y_min");
            var yMax = RequiredNumber(payload.GetProperty("y_max"), "y_max");
            if (xMin >= xMax || yMin >= yMax) throw new InvalidDataException("Axis range is invalid.");
            _ = RequiredText(payload.GetProperty("x_label"), "x_label", 80);
            _ = RequiredText(payload.GetProperty("y_label"), "y_label", 80);
        }
        else if (kind == "EQUATION")
        {
            RequireFields(payload, "output", "label", "expression");
            _ = RequiredIdentifier(payload.GetProperty("output"), "output");
            _ = RequiredText(payload.GetProperty("label"), "label", 500);
            ValidateExpression(payload.GetProperty("expression"), 0, new int[1]);
        }
        else if (kind == "GRAPH")
        {
            RequireFields(payload, "equation_id", "input_variable", "samples");
            _ = RequiredIdentifier(payload.GetProperty("equation_id"), "equation_id");
            var inputVariable = RequiredIdentifier(payload.GetProperty("input_variable"), "input_variable");
            var samples = payload.GetProperty("samples");
            if (samples.ValueKind != JsonValueKind.Array || samples.GetArrayLength() is < 2 or > 64)
                throw new InvalidDataException("Graph samples are outside bounds.");
            foreach (var sample in samples.EnumerateArray())
            {
                RequireFields(sample, "inputs", "output");
                var inputs = sample.GetProperty("inputs");
                if (inputs.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Graph inputs are invalid.");
                RejectDuplicateProperties(inputs);
                if (inputs.EnumerateObject().Count() > 16)
                    throw new InvalidDataException("Graph inputs exceed bounds.");
                if (!inputs.TryGetProperty(inputVariable, out _))
                    throw new InvalidDataException("Graph input variable is absent from a sample.");
                foreach (var input in inputs.EnumerateObject())
                {
                    if (!Identifier.IsMatch(input.Name)) throw new InvalidDataException("Graph variable is invalid.");
                    _ = RequiredNumber(input.Value, "graph input");
                }
                _ = RequiredNumber(sample.GetProperty("output"), "graph output");
            }
        }
        else if (kind == "NODE")
        {
            RequireFields(payload, "label", "x", "y");
            _ = RequiredText(payload.GetProperty("label"), "label", 200);
            RequiredUnit(payload.GetProperty("x"), "x"); RequiredUnit(payload.GetProperty("y"), "y");
        }
        else if (kind == "EDGE")
        {
            RequireFields(payload, "from_id", "to_id", "label");
            _ = RequiredIdentifier(payload.GetProperty("from_id"), "from_id");
            _ = RequiredIdentifier(payload.GetProperty("to_id"), "to_id");
            _ = RequiredText(payload.GetProperty("label"), "label", 200);
        }
        else
        {
            RequireFields(payload, "variable", "label", "min", "max", "step", "value");
            _ = RequiredIdentifier(payload.GetProperty("variable"), "variable");
            _ = RequiredText(payload.GetProperty("label"), "label", 120);
            var minimum = RequiredNumber(payload.GetProperty("min"), "min");
            var maximum = RequiredNumber(payload.GetProperty("max"), "max");
            var step = RequiredNumber(payload.GetProperty("step"), "step");
            var value = RequiredNumber(payload.GetProperty("value"), "value");
            if (minimum >= maximum || step <= 0 || value < minimum || value > maximum)
                throw new InvalidDataException("Slider range is invalid.");
            var offset=(value-minimum)/step;
            if(!double.IsFinite(offset)||Math.Abs(offset-Math.Round(offset))>1e-9)
                throw new InvalidDataException("Slider value is not aligned with its step.");
        }
    }

    private static void ValidateExpression(JsonElement node, int depth, int[] count)
    {
        if (++count[0] > 64 || depth > 8) throw new InvalidDataException("Expression exceeds bounds.");
        if (node.ValueKind != JsonValueKind.Object || !node.TryGetProperty("kind", out var kindNode))
            throw new InvalidDataException("Expression node is invalid.");
        var kind = RequiredText(kindNode, "expression kind", 16);
        if (kind == "CONSTANT")
        {
            RequireFields(node, "kind", "value"); _ = RequiredNumber(node.GetProperty("value"), "constant");
        }
        else if (kind == "VARIABLE")
        {
            RequireFields(node, "kind", "name"); _ = RequiredIdentifier(node.GetProperty("name"), "variable");
        }
        else if (kind == "OP")
        {
            RequireFields(node, "kind", "op", "args");
            var operation = RequiredText(node.GetProperty("op"), "operation", 8);
            if (!Operations.Contains(operation)) throw new InvalidDataException("Executable expression denied.");
            var args = node.GetProperty("args");
            var countExpected = operation switch
            {
                "ADD" or "MUL" or "MIN" or "MAX" => (Minimum: 2, Maximum: 8),
                _ => (Minimum: 2, Maximum: 2),
            };
            if (args.ValueKind != JsonValueKind.Array
                || args.GetArrayLength() < countExpected.Minimum
                || args.GetArrayLength() > countExpected.Maximum)
                throw new InvalidDataException("Expression arguments are outside bounds.");
            foreach (var argument in args.EnumerateArray()) ValidateExpression(argument, depth + 1, count);
            if (operation == "POW")
            {
                var exponent = args[1];
                if (exponent.GetProperty("kind").GetString() != "CONSTANT")
                    throw new InvalidDataException("Power exponent is not a bounded constant.");
                var number = RequiredNumber(exponent.GetProperty("value"), "power exponent");
                if (number < 0 || number > 8 || number != Math.Truncate(number))
                    throw new InvalidDataException("Power exponent is outside 0 through 8.");
            }
        }
        else throw new InvalidDataException("Executable expression denied.");
    }

    private static void ValidateSceneRelations(IReadOnlyList<TeachingPrimitive> primitives, JsonElement sliderValues)
    {
        var sliders=new Dictionary<string,double>(StringComparer.Ordinal);
        foreach(var item in primitives.Where(item=>item.Kind=="SLIDER"))
            if(!sliders.TryAdd(item.Payload.GetProperty("variable").GetString()!,RequiredNumber(item.Payload.GetProperty("value"),"slider value")))
                throw new InvalidDataException("Duplicate slider variable.");
        if(sliderValues.EnumerateObject().Count()!=sliders.Count
            || sliderValues.EnumerateObject().Any(p=>!sliders.TryGetValue(p.Name,out var value)||RequiredNumber(p.Value,"slider value")!=value))
            throw new InvalidDataException("Slider state does not match admitted primitives.");
        if(primitives.Any(item=>item.Kind=="GRAPH") && primitives.Count(item=>item.Kind=="AXES")!=1)
            throw new InvalidDataException("Graphs require one unambiguous common axes primitive.");
        var nodes = primitives.Where(item => item.Kind == "NODE")
            .Select(item => item.Id).ToHashSet(StringComparer.Ordinal);
        var equations = primitives.Where(item => item.Kind == "EQUATION")
            .ToDictionary(item => item.Id, item => item.Payload, StringComparer.Ordinal);
        foreach (var primitive in primitives)
        {
            if (primitive.Kind == "EDGE")
            {
                var from = primitive.Payload.GetProperty("from_id").GetString();
                var to = primitive.Payload.GetProperty("to_id").GetString();
                if (from is null || to is null || !nodes.Contains(from) || !nodes.Contains(to))
                    throw new InvalidDataException("Teaching edge endpoint is missing.");
            }
            if (primitive.Kind != "GRAPH") continue;
            var equationId = primitive.Payload.GetProperty("equation_id").GetString();
            if (equationId is null || !equations.TryGetValue(equationId, out var equation))
                throw new InvalidDataException("Teaching graph equation is missing.");
            var expression = equation.GetProperty("expression");
            var variables = ExpressionVariables(expression);
            var inputVariable = primitive.Payload.GetProperty("input_variable").GetString();
            if (inputVariable is null || !variables.Contains(inputVariable))
                throw new InvalidDataException("Graph input variable is absent from its equation.");
            foreach (var sample in primitive.Payload.GetProperty("samples").EnumerateArray())
            {
                var inputs = sample.GetProperty("inputs").EnumerateObject()
                    .ToDictionary(property => property.Name,
                        property => RequiredNumber(property.Value, "graph input"),
                        StringComparer.Ordinal);
                if (!variables.SetEquals(inputs.Keys))
                    throw new InvalidDataException("Graph sample variables do not match the equation.");
                if(sliders.Any(slider=>inputs.TryGetValue(slider.Key,out var value)&&value!=slider.Value))
                    throw new InvalidDataException("Graph samples contradict the admitted slider state.");
                var actual = EvaluateExpression(expression, inputs);
                var expected = RequiredNumber(sample.GetProperty("output"), "graph output");
                var tolerance = 1e-9 * Math.Max(1, Math.Max(Math.Abs(actual), Math.Abs(expected)));
                if (Math.Abs(actual - expected) > tolerance)
                    throw new InvalidDataException("Graph contradicts its deterministic equation.");
            }
        }
    }

    private static HashSet<string> ExpressionVariables(JsonElement expression)
    {
        var result = new HashSet<string>(StringComparer.Ordinal);
        void Walk(JsonElement node)
        {
            var kind = node.GetProperty("kind").GetString();
            if (kind == "VARIABLE") result.Add(node.GetProperty("name").GetString()!);
            else if (kind == "OP")
                foreach (var argument in node.GetProperty("args").EnumerateArray()) Walk(argument);
        }
        Walk(expression);
        return result;
    }

    private static double EvaluateExpression(JsonElement expression,
        IReadOnlyDictionary<string, double> variables)
    {
        var kind = expression.GetProperty("kind").GetString();
        if (kind == "CONSTANT") return RequiredNumber(expression.GetProperty("value"), "constant");
        if (kind == "VARIABLE") return variables[expression.GetProperty("name").GetString()!];
        var operation = expression.GetProperty("op").GetString();
        var values = expression.GetProperty("args").EnumerateArray()
            .Select(argument => EvaluateExpression(argument, variables)).ToArray();
        double result = operation switch
        {
            "ADD" => values.Sum(),
            "SUB" => values[0] - values[1],
            "MUL" => values.Aggregate(1.0, (total, value) => total * value),
            "DIV" => values[0] / values[1],
            "POW" => Math.Pow(values[0], values[1]),
            "MIN" => values.Min(),
            "MAX" => values.Max(),
            _ => throw new InvalidDataException("Unknown deterministic expression operation."),
        };
        if (!double.IsFinite(result) || Math.Abs(result) > 1_000_000_000)
            throw new InvalidDataException("Deterministic expression result is invalid.");
        return result;
    }

    private static void RequireFields(JsonElement element, params string[] expected)
    {
        if (element.ValueKind != JsonValueKind.Object) throw new InvalidDataException("JSON object required.");
        var allowed = new HashSet<string>(expected, StringComparer.Ordinal);
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in element.EnumerateObject())
            if (!seen.Add(property.Name) || !allowed.Contains(property.Name))
                throw new InvalidDataException("Unknown or duplicate teaching-scene field.");
        if (!seen.SetEquals(allowed)) throw new InvalidDataException("Teaching-scene fields are incomplete.");
    }

    private static void RejectDuplicateProperties(JsonElement element)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in element.EnumerateObject())
            if (!seen.Add(property.Name)) throw new InvalidDataException("Duplicate JSON property.");
    }

    private static string RequiredIdentifier(JsonElement value, string name)
    {
        var text = RequiredText(value, name, 128);
        if (!Identifier.IsMatch(text)) throw new InvalidDataException($"{name} is invalid.");
        return text;
    }

    private static string RequiredText(JsonElement value, string name, int maximum)
    {
        if (value.ValueKind != JsonValueKind.String) throw new InvalidDataException($"{name} has wrong type.");
        var text = value.GetString() ?? string.Empty;
        var characters=0;
        foreach(var rune in text.EnumerateRunes())characters++;
        if (string.IsNullOrWhiteSpace(text) || characters > maximum)
            throw new InvalidDataException($"{name} is invalid.");
        return text.Trim();
    }

    private static double RequiredNumber(JsonElement value, string name)
    {
        if (value.ValueKind != JsonValueKind.Number || !value.TryGetDouble(out var number)
            || !double.IsFinite(number) || Math.Abs(number) > 1_000_000_000)
            throw new InvalidDataException($"{name} is invalid.");
        return number;
    }

    private static void RequiredUnit(JsonElement value, string name)
    {
        var number = RequiredNumber(value, name);
        if (number is < 0 or > 1) throw new InvalidDataException($"{name} is outside 0..1.");
    }
}
