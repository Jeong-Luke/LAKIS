using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
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
                File.Exists(Path.Combine(root, "offer-complete")) ? "after offer" : "before offer");
            File.Move(result + ".tmp", result);
            return 0;
        }

        string scenario = args[0];
        string target = args[1];
        string version = scenario == "later-version" ? "8.1.4" : "8.1.3";
        bool launch = scenario == "failure" || scenario == "close" || scenario == "download-and-launch";
        bool eligible = scenario != "noninteractive" && scenario != "headless" && scenario != "repair" &&
            scenario != "later-version" && scenario != "other-source" && scenario != "no-handoff";
        bool runsPython = scenario == "download" || scenario == "download-and-launch" || scenario == "failure";
        var finishArgs = new List<string> { "--finish-self-update", target, version,
            scenario == "no-handoff" ? "0" : Int32.MaxValue.ToString() };
        // Legacy alias fallback must also work if the old process has exited.
        if (scenario != "download-and-launch") finishArgs.Add("--self-name=LAKIS_Patcher.exe");
        if (launch) finishArgs.Add("--launch-after-update");
        if (scenario == "headless" || scenario == "repair") finishArgs.Add("--" + scenario);

        int offers = 0, decisions = 0, downloads = 0;
        var warnings = new List<string>();
        string launcherResult = Path.Combine(target, "launcher-result");
        Action<string> offer = root => {
            ++offers;
            Require(root == target, "Offer received the wrong root.");
            CheckCommit(root, version);
            Require(!File.Exists(launcherResult), "Launcher ran before the offer.");
            bool ready = UpdaterForm.OfferSnapRefDownload(root, () => {
                ++decisions;
                if (scenario == "close") return DialogResult.Cancel;
                if (scenario == "retry" || scenario == "installed") return DialogResult.No;
                return DialogResult.Yes;
            }, info => {
                ++downloads;
                CheckDownloadInfo(root, info);
                UpdaterForm.WaitForSnapRefDownload(info);
            }, warnings.Add);
            Require(ready == (runsPython && scenario != "failure"),
                "Offer returned the wrong completion state.");
            File.WriteAllText(Path.Combine(root, "offer-complete"), "");
        };
        UpdaterForm.FinishSelfUpdate(finishArgs.ToArray(), scenario != "noninteractive", offer);
        CheckCommit(target, version);

        Require(offers == (eligible ? 1 : 0), "Wrong automatic offer count.");
        Require(decisions == (eligible ? 1 : 0), "Wrong decision count.");
        Require(downloads == (runsPython ? 1 : 0), "Python was started without an eligible affirmative decision.");
        Require(File.Exists(Path.Combine(target, "python-ran")) == runsPython, "Wrong installed Python execution count.");
        if (scenario == "failure" || scenario == "missing-script" || scenario == "linked-python")
        {
            Require(warnings.Count == 1 && warnings[0].Contains("LAKIS 업데이트는 완료되었습니다."),
                "An optional failure did not report that core succeeded.");
            if (scenario == "failure") Require(warnings[0].Contains("17"), "Missing downloader exit code.");
        }
        else Require(warnings.Count == 0, "Unexpected warning.");

        if (launch)
        {
            Require(SpinWait.SpinUntil(() => File.Exists(launcherResult), 5000), "Launcher did not run.");
            Require(File.ReadAllText(launcherResult) == "after offer", "Launcher preceded the optional step.");
        }
        else Require(!File.Exists(launcherResult), "Non-launching update started LAKIS.");

        if (scenario == "retry")
        {
            // No second finisher run or saved consent: a deliberate updater
            // retry on the now-current installation must ask again.
            bool ready = UpdaterForm.OfferSnapRefDownload(target, () => {
                ++decisions;
                return DialogResult.Yes;
            }, info => {
                ++downloads;
                CheckDownloadInfo(target, info);
                UpdaterForm.WaitForSnapRefDownload(info);
            }, warnings.Add);
            Require(ready && decisions == 2 && downloads == 1 && warnings.Count == 0,
                "Explicit retry did not make a fresh download decision.");
        }

        return 0;
    }

    private static void CheckCommit(string root, string version)
    {
        Require(File.ReadAllText(Path.Combine(root, "VERSION")).Trim() == version, "VERSION is not committed.");
        Require(File.ReadAllBytes(Path.Combine(root, "LAKIS_Patcher.exe")).SequenceEqual(
            File.ReadAllBytes(Application.ExecutablePath)), "Updater replacement is not committed.");
        Require(!Directory.EnumerateFiles(Path.Combine(root, ".lakis", "self-update-retired")).Any(),
            "Old updater retirement is still pending.");
    }

    private static void CheckDownloadInfo(string root, ProcessStartInfo info)
    {
        Require(info.FileName == Path.Combine(root, "python_embeded", "python.exe") &&
            info.WorkingDirectory == root && !info.UseShellExecute, "Wrong interpreter or working directory.");
    }

    private static int FakePython(string[] args)
    {
        string root = Directory.GetCurrentDirectory();
        Require(args.SequenceEqual(new[] {
            "-I", Path.Combine(root, "ComfyUI", "LAKIS", "install_snapref.py"),
            "--install-root", root, "--acknowledge-snapref-terms"
        }), "Wrong downloader arguments.");
        using (File.Create(Path.Combine(root, "python-ran"))) { }
        return File.Exists(Path.Combine(root, "fail-python")) ? 17 : 0;
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
