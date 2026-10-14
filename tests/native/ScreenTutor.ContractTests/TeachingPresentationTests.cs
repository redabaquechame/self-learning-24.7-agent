using System.IO;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;
using ScreenTutor;

internal static class TeachingPresentationTests
{
    internal static void ExitClears()
    {
        Exception? failure=null;
        var thread=new Thread(()=>
        {
            try
            {
                var window=new SessionWindow();
                var canvas=new TeachingCanvas();
                canvas.LoadRenderModel(File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory,"fixtures","tutor_canvas_render_v1.json")));
                typeof(SessionWindow).GetField("_teachingCanvas",BindingFlags.Instance|BindingFlags.NonPublic)!.SetValue(window,canvas);
                ((System.Windows.Controls.ContentControl)window.FindName("TeachingSceneHost")).Content=canvas;
                ((System.Windows.Controls.TextBlock)window.FindName("TeachingSceneAlternative")).Text=canvas.TextAlternative;
                typeof(SessionWindow).GetMethod("Exit_Click",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(window,[window,new System.Windows.RoutedEventArgs()]);
                if(canvas.TextAlternative!="" || ((System.Windows.Controls.ContentControl)window.FindName("TeachingSceneHost")).Content is not null)
                    throw new InvalidOperationException("actual Exit retained teaching content until a later timer tick");
            }
            catch(Exception error){failure=error;}
        });
        thread.SetApartmentState(ApartmentState.STA);thread.Start();
        if(!thread.Join(TimeSpan.FromSeconds(5)))throw new InvalidOperationException("owned Exit fixture did not finish");
        if(failure is not null)throw failure;
        Console.WriteLine("[canvas Exit] actual Exit clears scene content immediately; component fixture with no capture/provider");
    }
    internal static void StopClears()
    {
        Exception? failure=null;
        var thread=new Thread(()=>
        {
            try
            {
                var canvas=new TeachingCanvas();
                canvas.LoadRenderModel(File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory,"fixtures","tutor_canvas_render_v1.json")));
                canvas.BeginPracticeInk(new string('a',64));
                canvas.Stop();
                if (canvas.TextAlternative!="" || System.Windows.Automation.AutomationProperties.GetHelpText(canvas)!="")
                    throw new InvalidOperationException("stopped canvas retained source text or its accessible alternative");
            }
            catch(Exception error){failure=error;}
        });
        thread.SetApartmentState(ApartmentState.STA);thread.Start();
        if(!thread.Join(TimeSpan.FromSeconds(5)))throw new InvalidOperationException("owned canvas Stop fixture did not finish");
        if(failure is not null)throw failure;
        Console.WriteLine("[canvas Stop] content, source digest and accessible text cleared");
    }
    internal static void Contract()
    {
        if (typeof(NativeHostClient).GetMethod("SendTeachingQuestionAsync") is null)
            throw new InvalidOperationException("native typed teaching answer route is missing");
        var validate = typeof(TeachingCanvas).GetMethod("ValidateRenderModel", BindingFlags.Public | BindingFlags.Static)
            ?? throw new InvalidOperationException("native render validator is unavailable without a WPF control");
        var raw = File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory,"fixtures","tutor_presentation_bridge_v1.json"));
        var key = Enumerable.Range(0,32).Select(i=>(byte)i).ToArray();
        using var answer = BridgeCodec.Decode(key,raw,"bridge-session",1,1,0,2000);
        var presentation = answer.RootElement.GetProperty("body").GetProperty("presentation");
        if (presentation.GetProperty("qualification").GetString() != "LOCAL_ONLY")
            throw new InvalidOperationException("owned teaching fixture qualification changed");
        var model = JsonSerializer.SerializeToUtf8Bytes(presentation.GetProperty("render_model"));
        validate.Invoke(null,[new ReadOnlyMemory<byte>(model)]);
        void Refuses(Action operation)
        {
            try{operation();}
            catch(InvalidDataException){return;}
            throw new InvalidOperationException("invalid native teaching presentation was admitted");
        }
        foreach(var field in new[]{"qualification","learning_success_claimed","expires_at_monotonic_ms","request_id","executable_content"})
        {
            var changed=JsonNode.Parse(raw)!; changed.AsObject().Remove("mac");
            var scene=changed["body"]!["presentation"]!;
            if(field=="qualification")scene[field]="invented";
            else if(field=="learning_success_claimed")scene[field]=true;
            else if(field=="expires_at_monotonic_ms")scene[field]=8001;
            else if(field=="request_id")scene["binding"]![field]="foreign-request";
            else scene["render_model"]![field]=true;
            Refuses(()=>BridgeCodec.Encode(key,JsonSerializer.SerializeToElement(changed)));
        }
        var altered=JsonNode.Parse(raw)!; altered["body"]!["presentation"]!["qualification"]="REVIEWED_PACK";
        Refuses(()=>{using var _=BridgeCodec.Decode(key,JsonSerializer.SerializeToUtf8Bytes(altered),"bridge-session",1,1,0,2000);});
        Console.WriteLine("[presentation contract] actual Python-signed optional scene parsed by native codec and control-free semantic validator");
    }
}
