using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class SnapRefUpdaterFinisherContract
{
    private static readonly string[] OverlayPaths = {
        "ComfyUI/LAKIS/external_ui/index.html", "ComfyUI/LAKIS/external_ui/anima-reference.js",
        "ComfyUI/LAKIS/external_ui/anima-reference.css", "COMPLIANCE.md"
    };

    [STAThread]
    private static int Main(string[] args)
    {
        string executable = Path.GetFileName(Application.ExecutablePath);
        if (executable == "python.exe") return FakePython(args);
        if (args.Length == 1 && args[0] == "--stock-exit")
        {
            File.WriteAllText("old-updater-started", "");
            Thread.Sleep(1500);
            return 0;
        }
        if (executable == "LAKIS.exe")
        {
            string root = Directory.GetCurrentDirectory();
            string result = Path.Combine(root, "launcher-result");
            using (var sha = SHA256.Create())
                File.WriteAllLines(Path.Combine(root, "launcher-overlay"), OverlayPaths.Select(path =>
                    BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(Path.Combine(root, path)))).Replace("-", "")));
            File.WriteAllText(result + ".tmp",
                File.ReadAllText(Path.Combine(root, "VERSION")).Trim() + " " +
                File.Exists(Path.Combine(root, "snapref-ready")));
            File.Move(result + ".tmp", result);
            return 0;
        }

        string scenario = args[0];
        string target = args[1];
        string source = File.ReadAllText(Path.Combine(target, "VERSION")).Trim();
        string version = scenario == "later-version" ? "8.1.4" : "8.1.3.2";
        bool runtime = scenario.StartsWith("runtime-");
        bool badOverlay = scenario == "runtime-bad-overlay";
        bool badNotice = scenario == "notice-bad-asset" || scenario == "runtime-notice-bad-asset";
        bool reuseNotice = scenario == "notice-reuse" || scenario == "runtime-notice-reuse";
        bool restoreBlocked = scenario == "notice-restore-blocked" || scenario == "runtime-restore-blocked";
        bool preparationBlocked = scenario == "runtime-fails" || scenario == "runtime-bad-descriptor" ||
            badOverlay || badNotice;
        bool invalidHandoff = scenario == "too-old" || scenario == "already-target" || scenario == "no-handoff";
        bool unattended = scenario == "headless" || scenario == "repair" || scenario == "noninteractive";
        bool launch = scenario == "legacy-alias" || scenario == "stock-live" || scenario == "retry" || scenario == "cancel" ||
            badNotice || restoreBlocked || runtime && scenario != "runtime-no-launch";
        bool completes = scenario != "cancel" && scenario != "linked-python" && scenario != "bad-helper" &&
            !invalidHandoff && !preparationBlocked && !restoreBlocked;
        int expectedDownloads = scenario == "retry" ? 2 : (
            (runtime && !preparationBlocked || scenario == "stock" || scenario == "stock-live" || scenario == "legacy-alias" ||
             scenario == "cancel" || scenario == "missing-script" || scenario == "notice-reuse" ||
             scenario == "notice-restore-blocked") ? 1 : 0);
        string aliasPath = Path.Combine(target, "LAKIS_Patcher.exe");
        byte[] oldAlias = File.ReadAllBytes(aliasPath);
        Process parent = scenario == "stock-live" ? Process.Start(new ProcessStartInfo(aliasPath, "--stock-exit") {
            UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = target
        }) : null;
        if (parent != null)
            Require(SpinWait.SpinUntil(() => File.Exists(Path.Combine(target, "old-updater-started")), 5000),
                "Stock handoff process did not start.");
        var finishArgs = new List<string> { "--finish-self-update", target, version,
            parent != null ? parent.Id.ToString() : scenario == "no-handoff" ? "0" : Int32.MaxValue.ToString() };
        if (scenario != "legacy-alias") finishArgs.Add("--self-name=LAKIS_Patcher.exe");
        if (launch) finishArgs.Add("--launch-after-update");
        if (scenario == "headless" || scenario == "repair") finishArgs.Add("--" + scenario);

        int downloads = 0, transitions = 0, helperFetches = 0, descriptorFetches = 0, progressSessions = 0;
        int noticeFetches = 0;
        bool runtimeActivated = false;
        string noticePath = Path.Combine(target, "COMPLIANCE.md");
        byte[] previousNotice = File.ReadAllBytes(Path.Combine(args[4], "COMPLIANCE.md"));
        byte[] exactNotice = File.ReadAllBytes(args[5]);
        Require(File.ReadAllBytes(noticePath).SequenceEqual(previousNotice), "Stock patch pre-applied the notice.");
        if (reuseNotice) File.WriteAllBytes(noticePath, exactNotice);
        // An already verified notice on a direct update must not need write/delete access.
        FileStream overlayLock = !runtime && (reuseNotice || restoreBlocked)
            ? new FileStream(noticePath, FileMode.Open, FileAccess.Read, FileShare.Read) : null;
        var errors = new List<string>();
        var failures = new List<string>();
        var phases = new List<string>();
        bool regularWindow = false;
        string launcherResult = Path.Combine(target, "launcher-result");
        string helper = Path.Combine(target, "ComfyUI", "LAKIS", "install_snapref.py");
        byte[] exactHelper = File.ReadAllBytes(args[2]);
        Action pending = () => {
            Require(File.ReadAllText(Path.Combine(target, "VERSION")).Trim() == (runtimeActivated ? "8.1.3" : source),
                "VERSION was committed before preparation.");
            Require(File.ReadAllBytes(aliasPath).SequenceEqual(oldAlias),
                "Updater alias was replaced before preparation.");
            Require(!File.Exists(launcherResult), "Launcher ran before preparation.");
            Require(File.ReadAllBytes(noticePath).SequenceEqual(reuseNotice && !runtimeActivated
                ? exactNotice : previousNotice), "Notice was replaced before preparation completed.");
        };
        bool completed = UpdaterForm.FinishSelfUpdate(finishArgs.ToArray(), scenario != "noninteractive", info => {
            ++downloads;
            pending();
            Require(info.FileName == Path.Combine(target, "python_embeded", "python.exe") &&
                info.WorkingDirectory == target && !info.UseShellExecute, "Wrong interpreter or working directory.");
            Require(File.ReadAllBytes(helper).SequenceEqual(exactHelper), "Old or tampered helper was executed.");
            Require(progressSessions == 1, "Download ran outside the accepted update's progress session.");
            if (parent != null)
            {
                // Inspect the actual finisher form, not the simulated old process.
                var form = Application.OpenForms.Cast<Form>().SingleOrDefault();
                if (form != null)
                    regularWindow = (bool)form.Invoke((Func<bool>)(() => form is UpdaterForm && form.Visible &&
                        form.Text == "LAKIS 업데이트" && form.Controls.OfType<Button>().Count(button => button.Visible) == 1 &&
                        form.Controls.OfType<Label>().Any(label => label.Text.StartsWith("SnapRef"))));
            }
            UpdaterForm.WaitForSnapRefDownload(info);
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
            else if (asset == "COMPLIANCE.md")
            {
                ++noticeFetches;
                Require(!runtimeActivated && url ==
                    "https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.3.2/COMPLIANCE.md",
                    "Did not prepare the exact official notice before changing the runtime.");
                using (var sha = SHA256.Create())
                    Require(hash == BitConverter.ToString(sha.ComputeHash(exactNotice)).Replace("-", ""),
                        "Wrong notice pin.");
                File.WriteAllBytes(output, badNotice ? previousNotice : exactNotice);
            }
            else
            {
                ++descriptorFetches;
                Require(asset == "update-v4-latest.json" && url ==
                    "https://raw.githubusercontent.com/Jeong-Luke/LAKIS/39abe580a8238b21f84dc190e568cf2e58bc4d72/manifests/update-v4-latest.json",
                    "Did not fetch the exact published runtime descriptor.");
                File.WriteAllBytes(output, scenario == "runtime-bad-descriptor" ? new byte[0] : File.ReadAllBytes(args[3]));
            }
        }, (root, descriptor, report) => {
            pending();
            Require(root == target && runtime && helperFetches == 0, "Unexpected runtime transition.");
            ++transitions;
            report("runtime fixture progress");
            if (scenario == "runtime-fails") throw new IOException("activation failed");
            // Dispatch stub only. Native runtime preparation/activation is not
            // exercised by this test.
            foreach (string path in OverlayPaths)
                File.Copy(Path.Combine(args[4], path), Path.Combine(target, path), true);
            File.WriteAllText(Path.Combine(target, "VERSION"), "8.1.3");
            File.WriteAllText(Path.Combine(target, "LAKIS_Updater.exe"), "runtime alias");
            runtimeActivated = true;
            if (restoreBlocked)
                overlayLock = new FileStream(noticePath, FileMode.Open, FileAccess.Read, FileShare.Read);
        }, (root, finish) => {
            Require(root == target, "Wrong progress root.");
            ++progressSessions;
            if (parent != null)
            {
                Require(parent.HasExited, "Stock process was still alive when the progress form opened.");
                return UpdaterForm.RunSelfUpdateProgress(root, finish);
            }
            return finish(phases.Add, error => {
                pending();
                errors.Add(error);
                return scenario == "retry" && errors.Count == 1;
            }, failures.Add);
        }, failures.Add, failures.Add);
        if (overlayLock != null) overlayLock.Dispose();
        if (parent != null)
        {
            parent.Dispose();
            Require(regularWindow && Application.OpenForms.Count == 0,
                "Stock finisher did not use exactly one ordinary updater form with in-form status.");
        }

        Require(completed == completes, "Wrong finisher status.");
        bool hotfix = version == "8.1.3.2" && !invalidHandoff;
        bool hasProgress = !unattended && hotfix;
        Require(progressSessions == (hasProgress ? 1 : 0), "Wrong accepted progress session count.");
        if (runtime && !preparationBlocked)
            Require(phases.Count == 4 && phases[1] == "runtime fixture progress" &&
                phases[2].StartsWith("SnapRef"), "Runtime and SnapRef phases did not share one progress session.");
        Require(downloads == expectedDownloads, "Wrong downloader invocation count.");
        string runLog = Path.Combine(target, "python-ran");
        Require((File.Exists(runLog) ? File.ReadAllText(runLog).Length : 0) == expectedDownloads,
            "Wrong installed Python execution count.");
        Require(noticeFetches == (hotfix && !badOverlay && !reuseNotice ? 1 : 0), "Wrong notice download count.");
        Require(descriptorFetches == (runtime && !badOverlay && !badNotice ? 1 : 0), "Wrong descriptor download count.");
        Require(transitions == (runtime && !badOverlay && !badNotice && scenario != "runtime-bad-descriptor" ? 1 : 0),
            "Did not dispatch exactly one verified runtime transition.");
        Require(helperFetches == (hotfix && !preparationBlocked && scenario != "stock" ? 1 : 0),
            "Wrong helper download count.");
        Require(errors.Count == (scenario == "retry" || scenario == "cancel" ||
            scenario == "bad-helper" || scenario == "linked-python" ? 1 : 0), "Wrong preparation error count.");
        Require(failures.Count == (preparationBlocked || restoreBlocked || invalidHandoff ? 1 : 0),
            "Wrong finisher error count.");
        if (restoreBlocked)
        {
            Require(failures[0].Contains("COMPLIANCE.md") &&
                (!runtime || File.ReadAllText(Path.Combine(target, "LAKIS_Updater.exe")) == "runtime alias"),
                "Overlay restore failure lost its diagnostic or committed the updater sibling.");
        }
        if (badNotice)
            Require(failures[0].Contains("SHA-256") && failures[0].Contains("COMPLIANCE.md"),
                "Bad official notice was not rejected with a verification error.");
        if (badOverlay)
            Require(failures[0].Contains("SHA-256") && failures[0].Contains("index.html"),
                "Mismatched pre-applied overlay did not fail with a verification error.");
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
        string source = File.ReadAllText(Path.Combine(root, "VERSION")).Trim();
        bool adapted = source == "8.1.3.1";
        Require(adapted || source == "8.1.3", "Wrong source version.");
        Require(args.Take(3).SequenceEqual(new[] { "-I", "-X", "utf8" }) &&
            (adapted ? args.Length == 9 && args[3] == "-c" : args.Length == 7) &&
            args.Skip(adapted ? 5 : 3).SequenceEqual(new[] {
            Path.Combine(root, "ComfyUI", "LAKIS", "install_snapref.py"),
            "--install-root", root, "--provision-for-update"
        }), "Wrong helper arguments; update mode is not a manual acknowledgement.");
        if (adapted)
            File.WriteAllText(Path.Combine(root, "python-args.json"), new JavaScriptSerializer().Serialize(args));
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
