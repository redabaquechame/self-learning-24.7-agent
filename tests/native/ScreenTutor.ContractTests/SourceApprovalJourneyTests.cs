using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using ScreenTutor;

internal static class SourceApprovalJourneyTests
{
    internal static void Controls()
    {
        Exception? failure=null;
        var thread=new Thread(()=>
        {
            SessionWindow? window=null;
            try
            {
                window=new SessionWindow();
                if(window.FindName("ReturnToFleetButton") is not System.Windows.Controls.Button)
                    throw new InvalidOperationException("native session has no return to Fleet control");
                if(window.FindName("RetryAuthorizationButton") is not System.Windows.Controls.Button retry)
                    throw new InvalidOperationException("pending source has no explicit retry authorization control");
                if(retry.Visibility!=Visibility.Collapsed || retry.IsEnabled)
                    throw new InvalidOperationException("retry is available without a retained pending source");
                if(typeof(NativeHostClient).Assembly.GetType("ScreenTutor.SourceApprovalPendingException") is null)
                    throw new InvalidOperationException("native source approval pending is not distinguished from a lost source");
            }
            catch(Exception error){failure=error;}
            finally{window?.ExitCompanion();}
        });
        thread.SetApartmentState(ApartmentState.STA);thread.Start();
        if(!thread.Join(TimeSpan.FromSeconds(5)))throw new InvalidOperationException("owned pending UI fixture did not finish");
        if(failure is not null)throw failure;
        Console.WriteLine("[native pending source UI] explicit retry exists, unavailable before current pending source, typed pending response");
    }
}
