using System.IO;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using ScreenTutor;
using Point = System.Windows.Point;
using Size = System.Windows.Size;

internal static class TeachingReviewRepairTests
{
    private static JsonNode Model() => JsonNode.Parse(File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory,"fixtures","tutor_canvas_render_v1.json")))!;
    private static void Refuses(JsonNode value)
    {
        try{TeachingCanvas.ValidateRenderModel(JsonSerializer.SerializeToUtf8Bytes(value));}
        catch(InvalidDataException){return;}
        throw new InvalidOperationException("contradictory authenticated slider state admitted by native parser");
    }
    internal static void Sliders()
    {
        var model=Model();model["slider_values"]!["slope"]=3;Refuses(model);
        model=Model();model["slider_values"]!.AsObject().Remove("slope");Refuses(model);
        model=Model();model["slider_values"]!["foreign"]=1;Refuses(model);
        model=Model();var primitives=model["primitives"]!.AsArray();
        var slider=primitives.Single(p=>p!["kind"]!.GetValue<string>()=="SLIDER")!;
        var duplicate=slider.DeepClone();duplicate["id"]="second-slider";primitives.Add(duplicate);Refuses(model);
        model=Model();slider=model["primitives"]!.AsArray().Single(p=>p!["kind"]!.GetValue<string>()=="SLIDER")!;
        slider["payload"]!["value"]=2.25;model["slider_values"]!["slope"]=2.25;Refuses(model);
        model=Model();slider=model["primitives"]!.AsArray().Single(p=>p!["kind"]!.GetValue<string>()=="SLIDER")!;
        slider["payload"]!["value"]=3;model["slider_values"]!["slope"]=3;Refuses(model);
        Console.WriteLine("[review slider consistency] map/value/membership/duplicate/step/graph-state contradictions refused");
    }
    internal static void SignedBoundaries()
    {
        using var cases=JsonDocument.Parse(File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory,"fixtures","tutor_presentation_review_boundaries_v1.json")));
        var key=Enumerable.Range(0,32).Select(i=>(byte)i).ToArray();
        foreach(var item in cases.RootElement.EnumerateArray())
        {
            var accepted=false;
            try
            {
                using var result=BridgeCodec.Decode(key,System.Text.Encoding.UTF8.GetBytes(item.GetProperty("wire").GetString()!),"bridge-session",1,1,0,2000);
                accepted=true;
            }
            catch(InvalidDataException){}
            if(accepted!=item.GetProperty("allowed").GetBoolean())throw new InvalidOperationException("Signed boundary disagreement: "+item.GetProperty("name").GetString());
        }
        Console.WriteLine("[shared signed boundaries] seven Python-signed positive/negative limits and retirement fixtures agree");
    }
    internal static void Boundary(string mode)
    {
        var model=Model();
        if(mode=="unicode")
        {
            var text=model["primitives"]!.AsArray().Single(p=>p!["kind"]!.GetValue<string>()=="TEXT")!;
            text["payload"]!["text"]=string.Concat(Enumerable.Repeat("😀",1000));
            TeachingCanvas.ValidateRenderModel(JsonSerializer.SerializeToUtf8Bytes(model));
            text["payload"]!["text"]=string.Concat(Enumerable.Repeat("😀",1001));Refuses(model);
        }
        else
        {
            JsonNode expression=JsonNode.Parse("{\"kind\":\"VARIABLE\",\"name\":\"x\"}")!;
            for(var i=0;i<8;i++)expression=new JsonObject{["kind"]="OP",["op"]="ADD",["args"]=new JsonArray(expression,new JsonObject{["kind"]="CONSTANT",["value"]=0})};
            var equation=model["primitives"]!.AsArray().Single(p=>p!["kind"]!.GetValue<string>()=="EQUATION")!;
            equation["payload"]!["expression"]=expression;
            var graph=model["primitives"]!.AsArray().Single(p=>p!["kind"]!.GetValue<string>()=="GRAPH")!;
            foreach(var sample in graph["payload"]!["samples"]!.AsArray())
            {sample!["inputs"]!.AsObject().Remove("slope");sample["output"]=sample["inputs"]!["x"]!.GetValue<double>();}
            model["primitives"]!.AsArray().Remove(model["primitives"]!.AsArray().Single(p=>p!["kind"]!.GetValue<string>()=="SLIDER"));
            model["slider_values"]=new JsonObject();
            TeachingCanvas.ValidateRenderModel(JsonSerializer.SerializeToUtf8Bytes(model));
            equation["payload"]!["expression"]=new JsonObject{["kind"]="OP",["op"]="ADD",["args"]=new JsonArray(expression.DeepClone(),new JsonObject{["kind"]="CONSTANT",["value"]=0})};Refuses(model);
        }
        Console.WriteLine("[review scene boundary] valid "+mode+" limit accepted; immediately outside limit refused");
    }
    private static JsonNode GraphModel(double slope, bool constant)
    {
        var expr=new JsonObject{["kind"]="OP",["op"]="MUL",["args"]=new JsonArray(new JsonObject{["kind"]="CONSTANT",["value"]=slope},new JsonObject{["kind"]="VARIABLE",["name"]="x"})};
        JsonNode expression=constant ? new JsonObject{["kind"]="OP",["op"]="ADD",["args"]=new JsonArray(expr,new JsonObject{["kind"]="CONSTANT",["value"]=1})}:expr;
        return new JsonObject{["schema"]="tutor.canvas-render/1",["status"]="RENDER",["scene_id"]="graph-comparison",["text_alternative"]="Graph on common axes",["slider_values"]=new JsonObject(),["executable_content"]=false,
            ["primitives"]=new JsonArray(
                new JsonObject{["kind"]="AXES",["id"]="axes",["payload"]=new JsonObject{["x_min"]=0,["x_max"]=2,["y_min"]=0,["y_max"]=4,["x_label"]="x",["y_label"]="y"}},
                new JsonObject{["kind"]="EQUATION",["id"]="equation",["payload"]=new JsonObject{["expression"]=expression,["output"]="y",["label"]="Common axes"}},
                new JsonObject{["kind"]="GRAPH",["id"]="graph",["payload"]=new JsonObject{["equation_id"]="equation",["input_variable"]="x",["samples"]=new JsonArray(
                    new JsonObject{["inputs"]=new JsonObject{["x"]=0},["output"]=constant?1:0},new JsonObject{["inputs"]=new JsonObject{["x"]=2},["output"]=constant?1:2*slope})}})};
    }
    private static byte[] Paint(JsonNode model)
    {
        var canvas=new TeachingCanvas{Width=640,Height=360};canvas.LoadRenderModel(JsonSerializer.SerializeToUtf8Bytes(model));
        canvas.Measure(new Size(640,360));canvas.Arrange(new Rect(0,0,640,360));canvas.UpdateLayout();
        var bitmap=new RenderTargetBitmap(640,360,96,96,PixelFormats.Pbgra32);bitmap.Render(canvas);
        var pixels=new byte[640*360*4];bitmap.CopyPixels(pixels,640*4,0);canvas.Stop();return pixels;
    }
    private static bool Green(byte[] pixels,int x,int y)
    {
        for(var yy=y-2;yy<=y+2;yy++)for(var xx=x-2;xx<=x+2;xx++)
        {var i=(yy*640+xx)*4;if(pixels[i+3]>=200 && pixels[i+1]>=110 && pixels[i+2]<40 && pixels[i]<160)return true;}
        return false;
    }
    internal static void Graph(bool constant)
    {
        Exception? failure=null;
        var thread=new Thread(()=>
        {
            try
            {
                if(constant)
                {if(!Green(Paint(GraphModel(0,true)),330,228))throw new InvalidOperationException("valid constant function omitted from admitted axes");}
                else
                {
                    var first=Paint(GraphModel(1,false));var second=Paint(GraphModel(2,false));
                    if(!Green(first,330,228)||Green(first,330,166)||!Green(second,330,166))
                        throw new InvalidOperationException("different slopes paint identical normalized diagonals instead of admitted common axes");
                }
            }
            catch(Exception error){failure=error;}
        });thread.SetApartmentState(ApartmentState.STA);thread.Start();
        if(!thread.Join(TimeSpan.FromSeconds(5)))throw new InvalidOperationException("owned graph fixture stalled");
        if(failure is not null)throw failure;
        Console.WriteLine("[review graph fidelity] "+(constant?"constant horizontal function painted":"different slopes distinguished on admitted common axes"));
    }
    internal static void Reset()
    {
        Exception? failure=null;var thread=new Thread(()=>
        {
            try
            {
                var canvas=new TeachingCanvas();canvas.BeginPracticeInk(new string('a',64));
                typeof(TeachingCanvas).GetField("_activeStroke",BindingFlags.Instance|BindingFlags.NonPublic)!.SetValue(canvas,new List<Point>{new(10,10),new(20,20)});
                canvas.ResetPracticeInk();
                if(typeof(TeachingCanvas).GetField("_activeStroke",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(canvas) is not null)
                    throw new InvalidOperationException("clear notes retained the in-progress stroke for later restoration");
            }
            catch(Exception error){failure=error;}
        });thread.SetApartmentState(ApartmentState.STA);thread.Start();
        if(!thread.Join(TimeSpan.FromSeconds(5)))throw new InvalidOperationException("owned reset fixture stalled");
        if(failure is not null)throw failure;
        Console.WriteLine("[review reset] in-progress stroke discarded before later mouse-up");
    }
}
