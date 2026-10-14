using System.Text;
using System.Text.Json;
using ScreenTutor;

static class HumanPracticeWireTests
{
    public static void Controls()
    {
        if(typeof(NativeHostClient).GetMethod("PracticeAsync") is null) throw new InvalidDataException("Native practice client missing.");
        Exception? failure=null;
        var thread=new Thread(()=>
        {
            SessionWindow? window=null;
            try
            {
                window=new SessionWindow();
                foreach(var name in new[]{"PracticeStartButton","PracticeUploadButton","PracticeSubmitButton","PracticeCancelButton","PracticeRefreshButton"})
                {
                    if(window.FindName(name) is not System.Windows.Controls.Button button || button.IsEnabled)
                        throw new InvalidDataException("Practice control missing or enabled without host: "+name);
                }
                if(window.FindName("PracticeStatus") is not System.Windows.Controls.TextBlock text || !text.Text.Contains("unavailable"))
                    throw new InvalidDataException("Unconfigured practice status is misleading.");
            }
            catch(Exception error){failure=error;}
            finally{window?.ExitCompanion();}
        });
        thread.SetApartmentState(ApartmentState.STA);thread.Start();
        if(!thread.Join(TimeSpan.FromSeconds(5)))throw new InvalidDataException("Practice controls fixture timed out.");
        if(failure is not null)throw failure;
        Console.WriteLine("PASS native practice client and disabled unconfigured upload/submit/status/cancel controls");
    }
    public static void Run()
    {
        var constructor = typeof(BridgePeer).GetConstructor([typeof(byte[]), typeof(string), typeof(long), typeof(string), typeof(string)]);
        if (constructor is null) throw new InvalidDataException("Explicit practice protocol selection missing.");
        var key = Enumerable.Range(0,32).Select(x => (byte)x).ToArray();
        using var host = (BridgePeer)constructor.Invoke([key,"owned",1L,"HOST","1.2"]);
        using var native = (BridgePeer)constructor.Invoke([key,"owned",1L,"NATIVE","1.2"]);
        using var hello = native.Receive(host.Start(5000),1000);
        using var ack = host.Receive(native.Acknowledge(5000),1000);
        using var final = native.Receive(host.Acknowledge(5000),1000);
        var body = JsonSerializer.SerializeToElement(new { schema="fleet.tutor.practice-request.v1", operation="UPLOAD",
            payload=new { artifact_base64=Convert.ToBase64String(Encoding.UTF8.GetBytes("{\"total\":42}")) } });
        using var request = host.Receive(native.Send("PRACTICE_REQUEST",body,5000,null),1000);
        var id=request.RootElement.GetProperty("message_id").GetString();
        var result=JsonSerializer.SerializeToElement(new { schema="fleet.tutor.practice-result.v1",state="ACTIVE",attempt_id="attempt",artifact_count=1,
            predicate_correct=(bool?)null,passing=(bool?)null,independent_success=false,projection_status="UNASSESSED",qualification="UNASSESSED" });
        using var reply=native.Receive(host.Send("PRACTICE_RESULT",result,5000,id),1000);
        foreach(var invalid in new[] {
            "{\"schema\":\"fleet.tutor.practice-request.v1\",\"operation\":\"UPLOAD\",\"payload\":{\"artifact_digest\":\"fake\"}}",
            "{\"schema\":\"fleet.tutor.practice-request.v1\",\"operation\":\"UPLOAD\",\"payload\":{\"artifact_base64\":\"!\"}}",
            "{\"schema\":\"fleet.tutor.practice-request.v1\",\"operation\":\"START\",\"payload\":{\"project_id\":\"foreign\"}}" })
        {
            using var bad=JsonDocument.Parse(invalid);
            try { native.Send("PRACTICE_REQUEST",bad.RootElement,5000,null); }
            catch(InvalidDataException) { continue; }
            throw new InvalidDataException("Invalid practice payload admitted.");
        }
        using var old=new BridgePeer(key,"old",1,"NATIVE");
        using var newHost=(BridgePeer)constructor.Invoke([key,"old",1L,"HOST","1.2"]);
        try { using var skew=old.Receive(newHost.Start(5000),1000); }
        catch(InvalidDataException) { Console.WriteLine("PASS native practice1.2 exact agreement/bytes/closed scope/replies/version skew"); return; }
        throw new InvalidDataException("Version skew admitted.");
    }
}
