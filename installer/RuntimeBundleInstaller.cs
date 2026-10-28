using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;

internal sealed class RuntimeHandoff
{
    public string workspace { get; set; }
    public string target { get; set; }
    public string candidate { get; set; }
    public string cache { get; set; }
    public int previous_pid { get; set; }
    public long previous_start_ticks { get; set; }
    public string previous_executable { get; set; }
    public string manifest_sha256 { get; set; }
    public bool launch { get; set; }
}

internal static class RuntimeBundleInstaller
{
    private static readonly string[] Helpers = {
        "lakis_cmd_installer.py", "runtime_install.py", "runtime_transition.py",
        "runtime_manifest.py", "runtime_health.py", "runtime_patch.py", "runtime_update.py"
    };

    internal static string Quote(string value)
    {
        if (value == null || value.IndexOf('\0') >= 0) throw new ArgumentException("Invalid process argument.");
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char character in value)
        {
            if (character == '\\') { slashes++; continue; }
            result.Append('\\', character == '"' ? slashes * 2 + 1 : slashes);
            result.Append(character);
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        return result.Append('"').ToString();
    }

    internal static string HashFile(string path)
    {
        using (var stream = File.OpenRead(path)) return HashStream(stream);
    }

    private static string HashStream(Stream stream)
    {
        using (var hash = SHA256.Create())
            return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "");
    }

    private static void RejectReparse(string path)
    {
        string current = Path.GetFullPath(path);
        while (!String.IsNullOrEmpty(current))
        {
            if ((File.Exists(current) || Directory.Exists(current)) &&
                (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new IOException("Runtime helper path contains a reparse point: " + current);
            current = Path.GetDirectoryName(current);
        }
    }

    internal static string CreateWorkspace()
    {
        string path = Path.Combine(Path.GetTempPath(), "LAKIS-runtime-" + Guid.NewGuid().ToString("N"));
        RejectReparse(path);
        Directory.CreateDirectory(path);
        foreach (string name in Helpers)
        {
            using (var source = Assembly.GetExecutingAssembly().GetManifestResourceStream("LAKIS.Runtime." + name))
            {
                if (source == null) throw new InvalidDataException("Missing runtime helper resource: " + name);
                using (var output = new FileStream(Path.Combine(path, name), FileMode.CreateNew, FileAccess.Write))
                    source.CopyTo(output);
            }
        }
        return path;
    }

    internal static void VerifyHelpers(string workspace)
    {
        RejectReparse(workspace);
        foreach (string name in Helpers)
        {
            string path = Path.Combine(workspace, name);
            RejectReparse(path);
            using (var expected = Assembly.GetExecutingAssembly().GetManifestResourceStream("LAKIS.Runtime." + name))
            {
                if (expected == null || HashFile(path) != HashStream(expected))
                    throw new InvalidDataException("Runtime helper integrity mismatch: " + name);
            }
        }
    }

    internal static Dictionary<string, object> RunPython(
        string python, string workspace, IEnumerable<string> arguments, Action<string> report)
    {
        var quoted = new List<string>();
        foreach (string argument in arguments) quoted.Add(Quote(argument));
        var info = new ProcessStartInfo(python, String.Join(" ", quoted.ToArray())) {
            WorkingDirectory = workspace, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        string last = null;
        using (var process = Process.Start(info))
        {
            var errors = process.StandardError.ReadToEndAsync();
            string line;
            while ((line = process.StandardOutput.ReadLine()) != null)
            {
                if (!String.IsNullOrWhiteSpace(line)) last = line;
                report(line);
            }
            process.WaitForExit();
            string error = errors.GetAwaiter().GetResult();
            if (process.ExitCode != 0)
                throw new InvalidOperationException("Runtime transition failed (exit " + process.ExitCode +
                    "). Retained workspace: " + workspace + "\n" + error);
        }
        if (last == null) throw new InvalidDataException("Runtime helper returned no result.");
        return new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(last);
    }

    internal static RuntimeHandoff Prepare(
        string python, string manifestJson, string target, string cache, Action<string> report)
    {
        var update = UpdateProtocol.Read(manifestJson);
        if (update.kind != "runtime-update")
            throw new InvalidDataException("Expected a runtime-update manifest.");
        UpdateProtocol.ValidateForInstallation(update, File.ReadAllText(Path.Combine(target, "VERSION")).Trim());
        var handoff = CreateInstallContext(manifestJson, target, cache);
        string workspace = handoff.workspace;
        string manifest = Path.Combine(workspace, "manifest.json");
        var result = RunPython(python, workspace, new[] {
            "-s", Path.Combine(workspace, "runtime_update.py"), "--manifest", manifest,
            "--target", target, "--cache", cache,
            "--prepare-only"
        }, report);
        if (!result.ContainsKey("status") || (string)result["status"] != "prepared")
            throw new InvalidDataException("Runtime preparation did not finish.");
        handoff.candidate = Path.GetFullPath((string)result["candidate"]);
        VerifyManifest(handoff);
        VerifyCandidateEngine(handoff.candidate);
        return handoff;
    }

    internal static void VerifyCandidateEngine(string candidate)
    {
        // Inspect metadata only; do not execute candidate assemblies. Old
        // Preview bundles must not reinstall a legacy-channel updater.
        string updater = Path.Combine(candidate, "LAKIS_Updater.exe");
        string patcher = Path.Combine(candidate, "LAKIS_Patcher.exe");
        RejectReparse(updater);
        RejectReparse(patcher);
        if (HashFile(updater) != HashFile(patcher))
            throw new InvalidDataException("런타임의 두 업데이터 실행 파일이 일치하지 않습니다.");
        // Both updater aliases are the same assembly. Loading that identity
        // twice into the reflection-only context is rejected by .NET Framework.
        foreach (string name in new[] { "LAKIS.exe", "LAKIS_Updater.exe" })
        {
            string path = Path.Combine(candidate, name);
            RejectReparse(path);
            try
            {
                var assembly = Assembly.ReflectionOnlyLoad(File.ReadAllBytes(path));
                var protocol = assembly.GetType("UpdateProtocol", true);
                var flags = BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public;
                string engine = (string)protocol.GetField("EngineVersion", flags).GetRawConstantValue();
                int schema = (int)protocol.GetField("Schema", flags).GetRawConstantValue();
                if (schema != UpdateProtocol.Schema ||
                    UpdateProtocol.CompareVersions(engine, UpdateProtocol.EngineVersion) < 0)
                    throw new InvalidDataException("Candidate updater capability regressed.");
            }
            catch (Exception error)
            {
                throw new InvalidDataException("새 런타임에 호환되는 런처/업데이터가 없습니다: " + name, error);
            }
        }
    }

    private static RuntimeHandoff CreateInstallContext(string manifestJson, string target, string cache)
    {
        string workspace = CreateWorkspace();
        string manifest = Path.Combine(workspace, "manifest.json");
        File.WriteAllText(manifest, manifestJson, new UTF8Encoding(false));
        var handoff = new RuntimeHandoff {
            workspace = workspace, target = Path.GetFullPath(target), cache = Path.GetFullPath(cache),
            manifest_sha256 = HashFile(manifest)
        };
        VerifyHelpers(workspace);
        VerifyManifest(handoff);
        return handoff;
    }

    internal static Dictionary<string, object> Install(string python, string manifestJson,
        string target, string cache, string mode, bool includeAnimeSharp, Action<string> report)
    {
        if ((mode != "fresh" && mode != "repair") || (mode != "fresh" && includeAnimeSharp))
            throw new ArgumentException("Invalid GUI runtime installation mode.");
        var context = CreateInstallContext(manifestJson, target, cache);
        var arguments = new List<string> {
            "-s", Path.Combine(context.workspace, "runtime_install.py"),
            "--manifest", Path.Combine(context.workspace, "manifest.json"),
            "--target", context.target, "--cache", context.cache, "--mode", mode, "--method", "gui"
        };
        if (includeAnimeSharp) arguments.Add("--include-noncommercial-upscaler");
        var result = RunPython(python, context.workspace, arguments, report);
        VerifyManifest(context);
        if (!result.ContainsKey("status") || (string)result["status"] != "complete")
            throw new InvalidDataException("Runtime was not activated and verified.");
        return result;
    }

    internal static string WriteHandoff(RuntimeHandoff handoff, bool launch)
    {
        using (var parent = Process.GetCurrentProcess())
        {
            handoff.previous_pid = parent.Id;
            handoff.previous_start_ticks = parent.StartTime.ToUniversalTime().Ticks;
            handoff.previous_executable = Path.GetFullPath(parent.MainModule.FileName);
        }
        handoff.launch = launch;
        VerifyManifest(handoff);
        string path = Path.Combine(handoff.workspace, "handoff.json");
        using (var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write))
        using (var writer = new StreamWriter(stream, new UTF8Encoding(false)))
            writer.Write(new JavaScriptSerializer().Serialize(handoff));
        return path;
    }

    internal static RuntimeHandoff ReadHandoff(string path, string expectedHash)
    {
        RejectReparse(path);
        if (!System.Text.RegularExpressions.Regex.IsMatch(expectedHash ?? "", "^[A-Fa-f0-9]{64}$") ||
            !String.Equals(HashFile(path), expectedHash, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Runtime handoff identity mismatch.");
        var handoff = new JavaScriptSerializer().Deserialize<RuntimeHandoff>(File.ReadAllText(path, Encoding.UTF8));
        if (handoff == null || !String.Equals(Path.GetDirectoryName(Path.GetFullPath(path)),
                Path.GetFullPath(handoff.workspace), StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Runtime handoff workspace mismatch.");
        VerifyHelpers(handoff.workspace);
        VerifyManifest(handoff);
        string name = Path.GetFileName(handoff.previous_executable);
        if (name != "LAKIS_Updater.exe" && name != "LAKIS_Patcher.exe")
            throw new InvalidDataException("Unexpected updater parent executable.");
        return handoff;
    }

    internal static void WaitForParent(RuntimeHandoff handoff)
    {
        if (handoff.previous_pid <= 0 || handoff.previous_pid == Process.GetCurrentProcess().Id)
            throw new InvalidDataException("Invalid updater parent process.");
        Process parent;
        try { parent = Process.GetProcessById(handoff.previous_pid); }
        catch (ArgumentException) { return; }
        using (parent)
        {
            if (parent.HasExited) return;
            if (parent.StartTime.ToUniversalTime().Ticks != handoff.previous_start_ticks ||
                !String.Equals(Path.GetFullPath(parent.MainModule.FileName),
                    handoff.previous_executable, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Updater parent process identity changed.");
            if (!parent.WaitForExit(30000))
                throw new InvalidOperationException("The original updater has not exited; runtime was not replaced.");
        }
    }

    internal static void Apply(RuntimeHandoff handoff, Action<string> report, bool rollback = false)
    {
        WaitForParent(handoff);
        VerifyHelpers(handoff.workspace);
        VerifyManifest(handoff);
        var manifest = UpdateProtocol.Read(File.ReadAllText(Path.Combine(handoff.workspace, "manifest.json")));
        if (manifest.kind != "runtime-update")
            throw new InvalidDataException("Expected a runtime-update handoff.");
        VerifyCandidateEngine(handoff.candidate);
        var arguments = new List<string> {
            "-s", Path.Combine(handoff.workspace, "runtime_update.py"),
            "--manifest", Path.Combine(handoff.workspace, "manifest.json"),
            "--target", handoff.target, "--cache", handoff.cache,
            "--prepared-root", handoff.candidate
        };
        if (rollback) arguments.Add("--rollback");
        var result = RunPython(Path.Combine(handoff.candidate, "python_embeded", "python.exe"),
            handoff.workspace, arguments, report);
        if (!result.ContainsKey("status") || (string)result["status"] != (rollback ? "rolled-back" : "complete"))
            throw new InvalidDataException("Runtime was not activated and verified.");
    }

    private static void VerifyManifest(RuntimeHandoff handoff)
    {
        string path = Path.Combine(handoff.workspace, "manifest.json");
        RejectReparse(path);
        if (!String.Equals(HashFile(path), handoff.manifest_sha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Runtime installer manifest changed after preparation.");
    }
}
