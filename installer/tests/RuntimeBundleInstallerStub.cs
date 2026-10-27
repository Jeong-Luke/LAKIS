using System;
using System.Collections.Generic;
using System.IO;

internal static class RuntimeBundleInstaller
{
    internal static int Calls;
    internal static string Python;
    internal static string Manifest;
    internal static string Target;
    internal static string Cache;
    internal static string Mode;
    internal static bool IncludeAnimeSharp;

    internal static Dictionary<string, object> Install(string python, string manifestJson,
        string target, string cache, string mode, bool includeAnimeSharp, Action<string> report)
    {
        Calls++;
        Python = python;
        Manifest = manifestJson;
        Target = target;
        Cache = cache;
        Mode = mode;
        IncludeAnimeSharp = includeAnimeSharp;
        if(Environment.GetEnvironmentVariable("LAKIS_GUI_WIRING_TEST_FAIL")=="collision")
        {
            File.WriteAllText(Path.Combine(target,"network-install.log"),"concurrent-owner-log");
            File.WriteAllText(Path.Combine(target,"user-file.txt"),"concurrent-owner-data");
            throw new IOException("simulated target collision");
        }
        return new Dictionary<string, object> { { "status", "complete" } };
    }
}
