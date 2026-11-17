using System;
using System.Collections;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

internal static class FilePatch813NativeProbe
{
    private const BindingFlags Instance = BindingFlags.Instance | BindingFlags.NonPublic;
    private const BindingFlags Static = BindingFlags.Static | BindingFlags.NonPublic;

    [STAThread]
    private static int Main(string[] args)
    {
        if (Path.GetFileName(Application.ExecutablePath) == "LAKIS.exe")
        {
            File.WriteAllText(Path.Combine(Directory.GetCurrentDirectory(), "probe-relaunched"), "ok");
            return 0;
        }
        try
        {
            if (args[0] == "apply") Apply(args);
            else InspectLayout(args);
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            return 1;
        }
    }

    private static void Apply(string[] args)
    {
        var stock = Assembly.LoadFrom(args[1]);
        object patch = stock.GetType("UpdateProtocol").GetMethod("Read", Static)
            .Invoke(null, new object[] { File.ReadAllText(args[3]) });
        var type = stock.GetType("UpdaterForm");
        using (var form = (Form)Activator.CreateInstance(type, Instance, null,
            new object[] { args[2], false }, null))
        {
            var handle = form.Handle; // SetStatus needs a handle, but never display the form or run Shown.
            type.GetMethod("ApplyUpdate", Instance).Invoke(form, new[] { patch });
            Console.WriteLine(type.GetField("pendingSelfUpdate", Instance).GetValue(form));
        }
    }

    private static void InspectLayout(string[] args)
    {
        var startup = Assembly.LoadFrom(args[1]).GetType("LakisLauncher")
            .GetNestedType("StartupForm", BindingFlags.NonPublic);
        object[] metadata = { args[2], null, null, null };
        if (!(bool)startup.GetMethod("UsesReleaseLayout", Static).Invoke(null, new object[] { args[2] }) ||
            !(bool)startup.GetMethod("TryGetReleaseLayout", Static).Invoke(null, metadata))
            throw new InvalidDataException("Layout rejected: " + metadata[3]);
        var problems = (IList)startup.GetMethod("FindLayoutProblems", Static)
            .Invoke(null, new[] { args[2], metadata[1], false });
        foreach (string problem in problems) Console.WriteLine(problem);
        if (args[0] == "repair")
        {
            if (problems.Count == 0) throw new InvalidOperationException("No damage detected.");
            object[] repair = { args[2], metadata[1], metadata[2], null };
            if (!(bool)startup.GetMethod("ScheduleAutomaticRepair", Static).Invoke(null, repair))
                throw new InvalidDataException("Repair not scheduled: " + repair[3]);
        }
    }
}
