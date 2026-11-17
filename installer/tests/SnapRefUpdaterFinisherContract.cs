using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Windows.Forms;

internal static class SnapRefUpdaterFinisherContract
{
    [STAThread]
    private static int Main(string[] args)
    {
        string executable = Path.GetFileName(Application.ExecutablePath);
        if (executable == "python.exe") return FakePython(args);
        if (executable == "LAKIS.exe")
        {
            string root = Directory.GetCurrentDirectory();
            string result = Path.Combine(root, "launcher-result");
            File.WriteAllText(result + ".tmp",
                File.ReadAllText(Path.Combine(root, "VERSION")).Trim() + " " +
                File.Exists(Path.Combine(root, "snapref-ready")));
            File.Move(result + ".tmp", result);
            return 0;
        }

        string scenario = args[0];
        string target = args[1];
        string source = File.ReadAllText(Path.Combine(target, "VERSION")).Trim();
        string version = scenario == "later-version" ? "8.1.4" : "8.1.3.1";
        bool runtime = scenario.StartsWith("runtime-");
        bool runtimeFailure = scenario == "runtime-fails" || scenario == "runtime-bad-descriptor";
        bool launch = scenario == "legacy-alias" || scenario == "retry" || scenario == "cancel" ||
            runtime && scenario != "runtime-no-launch";
        bool completes = scenario != "cancel" && scenario != "linked-python" && scenario != "bad-helper" &&
            scenario != "too-old" && scenario != "no-handoff" && !runtimeFailure;
        int expectedDownloads = scenario == "retry" ? 2 : (
            (runtime && !runtimeFailure || scenario == "stock" || scenario == "legacy-alias" ||
             scenario == "cancel" || scenario == "missing-script") ? 1 : 0);
        var finishArgs = new List<string> { "--finish-self-update", target, version,
            scenario == "no-handoff" ? "0" : Int32.MaxValue.ToString() };
        if (scenario != "legacy-alias") finishArgs.Add("--self-name=LAKIS_Patcher.exe");
        if (launch) finishArgs.Add("--launch-after-update");
        if (scenario == "headless" || scenario == "repair") finishArgs.Add("--" + scenario);

        int downloads = 0, transitions = 0, helperFetches = 0, descriptorFetches = 0;
        bool runtimeActivated = false;
        var errors = new List<string>();
        var failures = new List<string>();
        string launcherResult = Path.Combine(target, "launcher-result");
        string helper = Path.Combine(target, "ComfyUI", "LAKIS", "install_snapref.py");
        byte[] exactHelper = File.ReadAllBytes(args[2]);
        Action pending = () => {
            Require(File.ReadAllText(Path.Combine(target, "VERSION")).Trim() == (runtimeActivated ? "8.1.3" : source),
                "VERSION was committed before preparation.");
            Require(File.ReadAllText(Path.Combine(target, "LAKIS_Patcher.exe")) == "old updater",
                "Updater alias was replaced before preparation.");
            Require(!File.Exists(launcherResult), "Launcher ran before preparation.");
        };
        bool completed = UpdaterForm.FinishSelfUpdate(finishArgs.ToArray(), scenario != "noninteractive", info => {
            ++downloads;
            pending();
            Require(info.FileName == Path.Combine(target, "python_embeded", "python.exe") &&
                info.WorkingDirectory == target && !info.UseShellExecute, "Wrong interpreter or working directory.");
            Require(File.ReadAllBytes(helper).SequenceEqual(exactHelper), "Old or tampered helper was executed.");
            UpdaterForm.WaitForSnapRefDownload(info);
        }, error => {
            pending();
            errors.Add(error);
            return scenario == "retry" && errors.Count == 1;
        }, (url, output, hash, asset) => {
            pending();
            if (asset == "install_snapref.py")
            {
                ++helperFetches;
                Require(!runtime || runtimeActivated, "Helper was fetched before runtime was activated.");
                Require(url == "https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.3.1/install_snapref.py",
                    "Did not fetch the hotfix asset.");
                File.WriteAllBytes(output, scenario == "bad-helper" ? new byte[0] : exactHelper);
            }
            else
            {
                ++descriptorFetches;
                Require(asset == "update-v4-latest.json" && url ==
                    "https://raw.githubusercontent.com/Jeong-Luke/LAKIS/39abe580a8238b21f84dc190e568cf2e58bc4d72/manifests/update-v4-latest.json",
                    "Did not fetch the exact published runtime descriptor.");
                File.WriteAllBytes(output, scenario == "runtime-bad-descriptor" ? new byte[0] : File.ReadAllBytes(args[3]));
            }
        }, (root, descriptor) => {
            pending();
            Require(root == target && runtime && helperFetches == 0, "Unexpected runtime transition.");
            ++transitions;
            if (scenario == "runtime-fails") throw new IOException("activation failed");
            // Dispatch stub only. Native runtime preparation/activation is not
            // exercised by this test.
            File.WriteAllText(Path.Combine(target, "VERSION"), "8.1.3");
            File.WriteAllText(Path.Combine(target, "LAKIS_Updater.exe"), "runtime alias");
            runtimeActivated = true;
        }, failures.Add);

        Require(completed == completes, "Wrong finisher status.");
        Require(downloads == expectedDownloads, "Wrong downloader invocation count.");
        string runLog = Path.Combine(target, "python-ran");
        Require((File.Exists(runLog) ? File.ReadAllText(runLog).Length : 0) == expectedDownloads,
            "Wrong installed Python execution count.");
        Require(descriptorFetches == (runtime ? 1 : 0), "Wrong descriptor download count.");
        Require(transitions == (runtime && scenario != "runtime-bad-descriptor" ? 1 : 0),
            "Did not dispatch exactly one verified runtime transition.");
        Require(helperFetches == (version == "8.1.3.1" && !runtimeFailure &&
            scenario != "too-old" && scenario != "no-handoff" ? 1 : 0), "Wrong helper download count.");
        Require(errors.Count == (scenario == "retry" || scenario == "cancel" ||
            scenario == "bad-helper" || scenario == "linked-python" ? 1 : 0), "Wrong preparation error count.");
        Require(failures.Count == (runtimeFailure || scenario == "too-old" || scenario == "no-handoff" ? 1 : 0),
            "Wrong finisher error count.");
        if (scenario == "cancel" || scenario == "retry")
            Require(errors[0].Contains("17") && errors[0].Contains("게시자 HTTP Error 503"),
                "Downloader failure lost the actual diagnostic.");
        if (scenario == "linked-python") Require(errors[0].Contains("연결된 경로"), "Linked path error lost.");
        if (scenario == "bad-helper")
        {
            Require(errors[0].Contains("SHA-256") && File.ReadAllText(helper) == "# old helper\n",
                "Bad hotfix asset replaced the old helper or lost its error.");
        }

        if (completes)
        {
            Require(File.ReadAllText(Path.Combine(target, "VERSION")).Trim() == version, "VERSION is not committed.");
            Require(File.ReadAllBytes(Path.Combine(target, "LAKIS_Patcher.exe")).SequenceEqual(
                File.ReadAllBytes(Application.ExecutablePath)), "Updater replacement is not committed.");
            Require(!Directory.EnumerateFiles(Path.Combine(target, ".lakis", "self-update-retired")).Any(),
                "Old updater retirement is still pending.");
            if (runtime)
                Require(File.ReadAllBytes(Path.Combine(target, "LAKIS_Updater.exe")).SequenceEqual(
                    File.ReadAllBytes(Application.ExecutablePath)), "Runtime overwrote the other hotfix alias.");
        }
        else pending();

        if (launch && completes)
        {
            Require(SpinWait.SpinUntil(() => File.Exists(launcherResult), 5000), "Launcher did not run.");
            Require(File.ReadAllText(launcherResult) == version + " True",
                "Launcher ran before the update and SnapRef preparation were complete.");
        }
        else Require(!File.Exists(launcherResult), "Unfinished or non-launching update started LAKIS.");
        return 0;
    }

    private static int FakePython(string[] args)
    {
        string root = Directory.GetCurrentDirectory();
        Require(args.SequenceEqual(new[] {
            "-I", "-X", "utf8", Path.Combine(root, "ComfyUI", "LAKIS", "install_snapref.py"),
            "--install-root", root, "--provision-for-update"
        }), "Wrong helper arguments; update mode is not a manual acknowledgement.");
        Require(File.ReadAllText(Path.Combine(root, "VERSION")).Trim() == "8.1.3", "Wrong source version.");
        File.AppendAllText(Path.Combine(root, "python-ran"), "x");
        string failOnce = Path.Combine(root, "fail-python-once");
        if (File.Exists(failOnce))
        {
            File.Delete(failOnce);
            byte[] diagnostic = Encoding.UTF8.GetBytes("게시자 HTTP Error 503: Service Unavailable\n");
            using (var stderr = Console.OpenStandardError()) stderr.Write(diagnostic, 0, diagnostic.Length);
            return 17;
        }
        File.WriteAllText(Path.Combine(root, "snapref-ready"), "");
        return 0;
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
