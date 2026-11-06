using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Web.Script.Serialization;

internal static class NativeEngineBridgeContract
{
    private static void Require(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }

    private static UpdateManifest Runtime(string version, string engine)
    {
        var manifest = new UpdateManifest {
            schema = 2, kind = "runtime-update", version = version,
            minimum_version = "7.5.4.1", minimum_updater_version = engine,
            files = new List<UpdateFile>(), delete = new List<string>(),
            runtime_bundle = new Dictionary<string, object> {
                { "schema", 2 }, { "product", "LAKIS" }, { "version", version },
                { "manifest_sha256", new string('A', 64) }
            }
        };
        return UpdateProtocol.Read(new JavaScriptSerializer().Serialize(manifest));
    }

    private static void Reject(Action action)
    {
        try { action(); }
        catch (InvalidDataException) { return; }
        throw new Exception("Expected an incompatible continuation to be rejected.");
    }

    private static int Main(string[] args)
    {
        Require(UpdateProtocol.IsRuntimeBridgeVersion("8.0.3.1"), "8.1 engine bridge missing.");
        Require(UpdateProtocol.IsRuntimeBridgeVersion("7.5.4.1"), "Legacy bridge lost.");
        Require(!UpdateProtocol.IsRuntimeBridgeVersion("8.0.3"), "Ordinary install is not a bridge.");
        Require(!UpdateProtocol.IsRuntimeBridgeVersion("8.1.0"), "Final install is not a bridge.");
        UpdateProtocol.ValidateRuntimeContinuation(Runtime("8.1.0", "8.1.0"), "8.0.3.1");
        UpdateProtocol.ValidateRuntimeContinuation(Runtime("8.0.0", "8.0.0"), "7.5.4.1");
        Reject(() => UpdateProtocol.ValidateRuntimeContinuation(Runtime("8.0.0", "8.0.0"), "8.0.3.1"));
        Reject(() => UpdateProtocol.ValidateRuntimeContinuation(Runtime("8.1.0", "8.1.0"), "8.0.3"));
        Reject(() => Runtime("8.1.0", "8.0.0"));
        var patch = new UpdateManifest { kind = "file-patch", version = "8.1.0",
            minimum_updater_version = "8.1.0" };
        Reject(() => UpdateProtocol.ValidateRuntimeContinuation(patch, "8.0.3.1"));
        Require(UpdateProtocol.ManifestUrls.SequenceEqual(new[] {
            "https://raw.githubusercontent.com/Jeong-Luke/LAKIS/main/manifests/update-v4-latest.json",
            "https://cdn.jsdelivr.net/gh/Jeong-Luke/LAKIS@main/manifests/update-v4-latest.json"
        }), "The new engine must not fetch the old engine's bootstrap channel again.");

        Environment.SetEnvironmentVariable("LAKIS_RC_MANIFEST_URL", null);
        Environment.SetEnvironmentVariable("LAKIS_RC_RUNTIME_MANIFEST_URL", null);
        var info = UpdaterForm.CreateRuntimeContinuation(args[0], true);
        Require(info.FileName == Path.Combine(args[0], "LAKIS_Updater.exe"), "Wrong updater target.");
        Require(info.Arguments.Contains("--continue-runtime-update"), "Continuation flag missing.");
        Require(info.Arguments.Contains("--launch-after-update"), "Launch intent lost.");
        Require(!info.UseShellExecute && info.WorkingDirectory == args[0], "Wrong launch scope.");

        Environment.SetEnvironmentVariable("LAKIS_RC_MANIFEST_URL", "http://127.0.0.1:18301/bridge.json");
        Environment.SetEnvironmentVariable("LAKIS_RC_RUNTIME_MANIFEST_URL", "http://127.0.0.1:18301/runtime.json");
        info = UpdaterForm.CreateRuntimeContinuation(args[0], true);
        Require(info.EnvironmentVariables["LAKIS_RC_MANIFEST_URL"] ==
            "http://127.0.0.1:18301/runtime.json", "RC continuation reused the bootstrap manifest.");
        Environment.SetEnvironmentVariable("LAKIS_RC_RUNTIME_MANIFEST_URL", null);
        Reject(() => UpdaterForm.CreateRuntimeContinuation(args[0], true));
        Console.WriteLine("PASS: native bridge versions, channel separation, continuation and fail-closed routing.");
        return 0;
    }
}
