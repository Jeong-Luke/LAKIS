using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

internal static class LakisLauncher
{
    private static readonly string[] ManifestUrls = {
        "https://raw.githubusercontent.com/Jeong-Luke/LAKIS/main/manifests/update-latest.json",
        "https://cdn.jsdelivr.net/gh/Jeong-Luke/LAKIS@main/manifests/update-latest.json"
    };
    private const string LatestReleaseApiUrl = "https://api.github.com/repos/Jeong-Luke/LAKIS/releases/latest";

    private static bool TryGetLatestVersion(out Version latest, out string failure)
    {
        latest = null;
        failure = "업데이트 서버에 연결할 수 없습니다.";
        ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
        foreach (string url in ManifestUrls)
        {
            try
            {
                var request = (HttpWebRequest)WebRequest.Create(url + "?t=" + DateTimeOffset.UtcNow.ToUnixTimeSeconds());
                request.UserAgent = "LAKIS-Launcher/7.1.3";
                request.Timeout = 12000;
                request.ReadWriteTimeout = 12000;
                request.AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate;
                request.CachePolicy = new System.Net.Cache.RequestCachePolicy(System.Net.Cache.RequestCacheLevel.NoCacheNoStore);
                string json;
                using (var response = request.GetResponse())
                using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8, true)) json = reader.ReadToEnd();
                Match match = Regex.Match(json, "\\\"version\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"");
                Version parsed;
                if (match.Success && Version.TryParse(match.Groups[1].Value, out parsed)) { latest = parsed; return true; }
                failure = "업데이트 서버가 올바르지 않은 버전 정보를 반환했습니다.";
            }
            catch (Exception error) { failure = error.Message; }
        }
        // The manifest hosts can be cached or blocked independently.  GitHub's
        // release API is a third, metadata-only route, so a launcher never gets
        // stranded merely because raw.githubusercontent.com is unavailable.
        try
        {
            var request = (HttpWebRequest)WebRequest.Create(LatestReleaseApiUrl + "?t=" + DateTimeOffset.UtcNow.ToUnixTimeSeconds());
            request.UserAgent = "LAKIS-Launcher/7.1.3";
            request.Accept = "application/vnd.github+json";
            request.Timeout = 12000;
            request.ReadWriteTimeout = 12000;
            request.AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate;
            string json;
            using (var response = request.GetResponse())
            using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8, true)) json = reader.ReadToEnd();
            Match match = Regex.Match(json, "\\\"tag_name\\\"\\s*:\\s*\\\"v?([^\\\"]+)\\\"");
            Version parsed;
            if (match.Success && Version.TryParse(match.Groups[1].Value, out parsed)) { latest = parsed; return true; }
            failure = "GitHub 릴리스가 올바르지 않은 버전 정보를 반환했습니다.";
        }
        catch (Exception error) { failure = error.Message; }
        return false;
    }

    [STAThread]
    private static void Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, "python_embeded", "pythonw.exe");
        string launcher = Path.Combine(root, "ComfyUI", "LAKIS_DEV", "external_ui", "launch_lakis.py");
        if (!File.Exists(python) || !File.Exists(launcher))
        {
            MessageBox.Show("LAKIS 실행 파일을 찾을 수 없습니다. 설치를 다시 진행해 주세요.",
                "LAKIS 실행 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        try
        {
            string patcher = Path.Combine(root, "LAKIS_Patcher.exe");
            string updater = File.Exists(patcher) ? patcher : Path.Combine(root, "LAKIS_Updater.exe");
            string currentPath = Path.Combine(root, "VERSION");
            string currentText = File.Exists(currentPath) ? File.ReadAllText(currentPath).Trim() : "0.0.0";
            Version current, latest;
            if (!Version.TryParse(currentText, out current)) current = new Version(0, 0, 0);
            string updateFailure;
            bool updateChecked = TryGetLatestVersion(out latest, out updateFailure);
            if (!updateChecked)
                MessageBox.Show("업데이트 확인에 실패했습니다. LAKIS는 계속 실행됩니다.\n\n" + updateFailure,
                    "LAKIS 업데이트", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            if (File.Exists(updater) && updateChecked && latest > current
                && MessageBox.Show("새로운 LAKIS 업데이트가 있습니다.\n지금 업데이트할까요?",
                    "LAKIS 업데이트", MessageBoxButtons.YesNo, MessageBoxIcon.Information) == DialogResult.Yes)
            {
                Process.Start(new ProcessStartInfo {
                    FileName = updater,
                    Arguments = "\"" + root.TrimEnd(Path.DirectorySeparatorChar) + "\" --launch-after-update",
                    WorkingDirectory = root,
                    UseShellExecute = true,
                });
                return;
            }
            var startInfo = new ProcessStartInfo {
                FileName = python,
                Arguments = "-s \"" + launcher + "\"",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            // LoRA Manager normally stores one settings/cache directory per
            // Windows account.  That makes separate ComfyUI installations leak
            // stale model paths into LAKIS.  Pin it to this LAKIS installation
            // so moves and scans are always validated against this runtime.
            startInfo.EnvironmentVariables["LORA_MANAGER_SETTINGS_DIR"] =
                Path.Combine(root, "ComfyUI", "user", "default", "lora-manager");
            Process.Start(startInfo);
        }
        catch (Exception error)
        {
            MessageBox.Show("LAKIS를 실행하지 못했습니다.\n\n" + error.Message,
                "LAKIS 실행 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
