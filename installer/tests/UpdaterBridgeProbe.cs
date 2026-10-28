using System;
using System.IO;
using System.Reflection;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class UpdaterBridgeProbe
{
    private static readonly BindingFlags Methods = BindingFlags.NonPublic | BindingFlags.Public |
        BindingFlags.Static | BindingFlags.Instance;

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            if (args[0] == "--finish-self-update")
            {
                typeof(UpdaterForm).GetMethod("Main", Methods).Invoke(null, new object[] { args });
                return 0;
            }
            if (Array.Exists(args, value => value == "--continue-runtime-update"))
            {
                // Observe the real child handoff and manifest fetch without
                // claiming a full runtime transaction in this native fixture.
                string target = args[0];
                using (var form = new UpdaterForm(target, false))
                {
                    var manifest = (UpdateManifest)typeof(UpdaterForm)
                        .GetMethod("DownloadManifest", Methods).Invoke(form, null);
                    string installed = File.ReadAllText(Path.Combine(target, "VERSION")).Trim();
                    UpdateProtocol.ValidateRuntimeContinuation(manifest, installed);
                    File.WriteAllText(Path.Combine(target, "runtime-continuation.json"),
                        new JavaScriptSerializer().Serialize(new {
                            version = manifest.version, installed_version = installed,
                            engine = UpdateProtocol.EngineVersion,
                            launch = Array.Exists(args, value => value == "--launch-after-update"),
                            manifest_url = Environment.GetEnvironmentVariable("LAKIS_RC_MANIFEST_URL")
                        }));
                }
                return 0;
            }
            if (args[0] == "continuation-info")
            {
                Environment.SetEnvironmentVariable("LAKIS_RC_MANIFEST_URL", args[3]);
                Environment.SetEnvironmentVariable("LAKIS_RC_RUNTIME_MANIFEST_URL", args[4]);
                var info = UpdaterForm.CreateRuntimeContinuation(args[1], args[2] == "true");
                Console.WriteLine(new JavaScriptSerializer().Serialize(new {
                    file = info.FileName, arguments = info.Arguments,
                    manifest_url = info.EnvironmentVariables["LAKIS_RC_MANIFEST_URL"]
                }));
                return 0;
            }
            if (args[0] == "defaults")
            {
                foreach (Type type in new[] { typeof(UpdaterForm), typeof(LakisLauncher) })
                    Console.WriteLine(String.Join("|", (string[])type.GetField("ManifestUrls", Methods).GetValue(null)));
                return 0;
            }
            if (args[0] == "assembly-defaults")
            {
                Assembly inspectedAssembly = Assembly.LoadFrom(args[1]);
                Type protocol = inspectedAssembly.GetType("UpdateProtocol", true);
                Console.WriteLine(String.Join("|",
                    (string[])protocol.GetField("ManifestUrls", Methods).GetValue(null)));
                return 0;
            }
            if (args[0] == "version-display")
            {
                using (var form = new UpdaterForm(args[1], false))
                {
                    var label = (Label)typeof(UpdaterForm).GetField("copyright", Methods).GetValue(form);
                    Console.WriteLine(label.Text);
                    for (int index = 2; index < args.Length; index++)
                    {
                        File.WriteAllText(Path.Combine(args[1], "VERSION"), args[index]);
                        typeof(UpdaterForm).GetMethod("RefreshInstalledVersion", Methods).Invoke(form, null);
                        Console.WriteLine(label.Text);
                    }
                }
                return 0;
            }
            if (args[0] == "protocol" || args[0] == "continuation-protocol")
            {
                var manifest = UpdateProtocol.Read(File.ReadAllText(args[1]));
                UpdateProtocol.ValidateForInstallation(manifest, args[2]);
                if (args[0] == "continuation-protocol")
                    UpdateProtocol.ValidateRuntimeContinuation(manifest, args[2]);
                Console.WriteLine(manifest.version);
                return 0;
            }
            if (args[0] == "guard")
            {
                UpdateProtocol.EnsureNoPendingRuntimeTransition(args[1]);
                return 0;
            }
            if (args[0] == "candidate-engine")
            {
                RuntimeBundleInstaller.VerifyCandidateEngine(args[1]);
                return 0;
            }
            if (args[0] == "runtime-health")
            {
                string workspace = RuntimeBundleInstaller.CreateWorkspace();
                RuntimeBundleInstaller.VerifyHelpers(workspace);
                RuntimeBundleInstaller.RunPython(Path.Combine(args[1], "python_embeded", "python.exe"),
                    workspace, new[] { "-s", Path.Combine(workspace, "runtime_health.py"), "--root", args[1] },
                    Console.WriteLine);
                return 0;
            }
            if (args[0] == "progress-window")
            {
                // Visual-only fixture: replay one recorded engine progress line.
                // Do not download, apply an update, or claim a live transaction.
                var lines = Array.FindAll(File.ReadAllLines(args[2]),
                    line => line.StartsWith("[준비] 프로그램 파일 ", StringComparison.Ordinal));
                if (lines.Length == 0) throw new InvalidDataException("No recorded progress lines.");
                string sample = lines[lines.Length / 2];
                Application.EnableVisualStyles();
                using (var form = new UpdaterForm(args[1], false))
                {
                    typeof(UpdaterForm).GetField("started", Methods).SetValue(form, true);
                    form.Text = "LAKIS 진행표시 격리 시험";
                    form.Shown += (_, __) => typeof(UpdaterForm).GetMethod("ReportRuntimeProgress", Methods)
                        .Invoke(form, new object[] { sample });
                    Console.WriteLine("GUI_PROGRESS_SAMPLE=" + sample);
                    Application.Run(form);
                }
                return 0;
            }
            if (args[0] == "helpers")
            {
                string workspace = RuntimeBundleInstaller.CreateWorkspace();
                RuntimeBundleInstaller.VerifyHelpers(workspace);
                if (args.Length > 1)
                {
                    File.AppendAllText(Path.Combine(workspace, args[1]), "\n# modified\n");
                    RuntimeBundleInstaller.VerifyHelpers(workspace);
                }
                Console.WriteLine(workspace);
                return 0;
            }
            if (args[0] == "runtime-prepare-gui")
            {
                RuntimeHandoff prepared = null;
                Exception failure = null;
                Application.EnableVisualStyles();
                using (var form = new UpdaterForm(args[3], false))
                {
                    typeof(UpdaterForm).GetField("started", Methods).SetValue(form, true);
                    form.Text = "LAKIS 격리 인터넷 준비 시험";
                    var busy = typeof(UpdaterForm).GetField("runtimeBusy", Methods);
                    var progress = typeof(UpdaterForm).GetMethod("ReportRuntimeProgress", Methods);
                    form.Shown += async (_, __) => {
                        busy.SetValue(form, true);
                        try
                        {
                            prepared = await Task.Run(() => RuntimeBundleInstaller.Prepare(
                                args[1], File.ReadAllText(args[2]), args[3], args[4], line => {
                                    Console.WriteLine(line);
                                    progress.Invoke(form, new object[] { line });
                                }));
                        }
                        catch (Exception error) { failure = error; }
                        finally { busy.SetValue(form, false); form.Close(); }
                    };
                    Application.Run(form);
                }
                if (failure != null) throw failure;
                string path = RuntimeBundleInstaller.WriteHandoff(prepared, false);
                Console.WriteLine(new JavaScriptSerializer().Serialize(new {
                    path = path, sha256 = RuntimeBundleInstaller.HashFile(path)
                }));
                return 0;
            }
            if (args[0] == "runtime-prepare")
            {
                var handoff = RuntimeBundleInstaller.Prepare(args[1], File.ReadAllText(args[2]),
                    args[3], args[4], Console.WriteLine);
                string path = RuntimeBundleInstaller.WriteHandoff(handoff, false);
                Console.WriteLine(new JavaScriptSerializer().Serialize(new {
                    path = path, sha256 = RuntimeBundleInstaller.HashFile(path)
                }));
                return 0;
            }
            if (args[0] == "runtime-apply" || args[0] == "runtime-recover")
            {
                var handoff = RuntimeBundleInstaller.ReadHandoff(args[1], args[2]);
                RuntimeBundleInstaller.Apply(handoff, Console.WriteLine, args[0] == "runtime-recover");
                return 0;
            }
            if (args[0] == "launcher")
            {
                Environment.SetEnvironmentVariable("LAKIS_RC_MANIFEST_URL", args[1]);
                object[] values = { null, null };
                bool ok = (bool)typeof(LakisLauncher).GetMethod("TryGetLatestVersion", Methods).Invoke(null, values);
                Console.WriteLine(ok ? values[0] : values[1]);
                return ok ? 0 : 2;
            }
            string root = args[1];
            Environment.SetEnvironmentVariable("LAKIS_RC_MANIFEST_URL", args[2]);
            Environment.SetEnvironmentVariable("LAKIS_RC_RELEASE_BASE_URL", new Uri(args[2]).GetLeftPart(UriPartial.Authority));
            bool legacy = args[0].StartsWith("legacy-", StringComparison.Ordinal);
            Assembly assembly = legacy ? Assembly.LoadFrom(args[3]) : typeof(UpdaterForm).Assembly;
            Type updaterType = assembly.GetType("UpdaterForm", true);
            if (args[0] == "legacy-catalog")
            {
                object manifest = new JavaScriptSerializer().Deserialize(
                    File.ReadAllText(args[4]), assembly.GetType("UpdateManifest", true));
                int count = 0;
                foreach (object file in (System.Collections.IEnumerable)manifest.GetType().GetProperty("files").GetValue(manifest, null))
                {
                    string path = (string)file.GetType().GetProperty("path").GetValue(file, null);
                    updaterType.GetMethod("ValidateRelativePath", Methods).Invoke(null, new object[] { path });
                    count++;
                }
                foreach (string path in (System.Collections.IEnumerable)manifest.GetType().GetProperty("delete").GetValue(manifest, null))
                    if ((bool)updaterType.GetMethod("IsProtected", Methods).Invoke(null, new object[] { path }))
                        throw new InvalidDataException("Protected deletion in bridge manifest.");
                Console.WriteLine(count);
                return 0;
            }
            using (var form = (Form)Activator.CreateInstance(updaterType,
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
                null, new object[] { root, false }, null))
            {
                if (args[0].EndsWith("-read", StringComparison.Ordinal))
                {
                    object manifest = updaterType.GetMethod("DownloadManifest", Methods).Invoke(form, null);
                    Console.WriteLine(new JavaScriptSerializer().Serialize(manifest));
                    return 0;
                }
                var handle = form.Handle;
                string document = File.ReadAllText(args[legacy ? 4 : 3]);
                object update = new JavaScriptSerializer().Deserialize(document, assembly.GetType("UpdateManifest", true));
                // A model locked against all other access must not be read,
                // copied or hashed by a program-only update.
                using (var locked = new FileStream(Path.Combine(root, "ComfyUI", "models", "fixture.bin"),
                    FileMode.Open, FileAccess.ReadWrite, FileShare.None))
                    updaterType.GetMethod("ApplyUpdate", Methods).Invoke(form, new[] { update });
                Console.WriteLine("PENDING=" + (string)updaterType.GetField("pendingSelfUpdate", Methods).GetValue(form));
                return 0;
            }
        }
        catch (Exception error)
        {
            if (error is TargetInvocationException && error.InnerException != null) error = error.InnerException;
            Console.Error.WriteLine(error.GetType().Name + ": " + error.Message);
            return 1;
        }
    }
}
