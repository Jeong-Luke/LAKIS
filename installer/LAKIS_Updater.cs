using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal sealed class UpdateFile
{
    public string path { get; set; }
    public string url { get; set; }
    public string sha256 { get; set; }
}

internal sealed class UpdateManifest
{
    public string version { get; set; }
    public string minimum_version { get; set; }
    public string release_notes { get; set; }
    public List<UpdateFile> files { get; set; }
    public List<string> delete { get; set; }
}

internal sealed class UpdaterForm : Form
{
    private static readonly string[] ManifestUrls = {
        "https://raw.githubusercontent.com/Jeong-Luke/LAKIS/main/manifests/update-latest.json",
        "https://cdn.jsdelivr.net/gh/Jeong-Luke/LAKIS@main/manifests/update-latest.json"
    };
    private readonly Label status = new Label();
    private readonly ProgressBar progress = new ProgressBar();
    private readonly Button update = new Button();
    private readonly string targetRoot;
    private readonly bool launchAfterUpdate;
    private string pendingSelfUpdate;

    internal UpdaterForm(string root, bool launchWhenFinished = false)
    {
        targetRoot = Path.GetFullPath(root);
        launchAfterUpdate = launchWhenFinished;
        Text = "LAKIS 업데이트";
        Width = 540; Height = 220; FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false; StartPosition = FormStartPosition.CenterScreen;
        Controls.Add(new Label { Left = 24, Top = 22, Width = 480, Height = 32, Text = "LAKIS Studio 업데이트", Font = new System.Drawing.Font("Segoe UI", 16, System.Drawing.FontStyle.Bold) });
        status.Left = 26; status.Top = 72; status.Width = 480; status.Height = 38; status.Text = "업데이트 확인 준비 완료";
        progress.Left = 26; progress.Top = 116; progress.Width = 480; progress.Height = 18;
        update.Left = 396; update.Top = 148; update.Width = 110; update.Height = 30; update.Text = "확인";
        update.Click += async (_, __) => await UpdateAsync();
        Controls.AddRange(new Control[] { status, progress, update });
    }

    private async Task UpdateAsync()
    {
        update.Enabled = false; progress.Value = 0;
        try
        {
            if (!File.Exists(Path.Combine(targetRoot, "LAKIS.exe")) || !Directory.Exists(Path.Combine(targetRoot, "ComfyUI")))
                throw new DirectoryNotFoundException("LAKIS 설치 위치를 찾을 수 없습니다: " + targetRoot);
            status.Text = "업데이트 정보를 확인하고 있습니다…";
            UpdateManifest manifest = await Task.Run(() => DownloadManifest());
            string current = ReadCurrentVersion();
            if (CompareVersions(manifest.version, current) <= 0)
            {
                status.Text = "최신 버전입니다. (v" + current + ")";
                MessageBox.Show("현재 LAKIS가 최신 버전입니다.", "LAKIS 업데이트", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            if (MessageBox.Show("v" + manifest.version + " 업데이트가 있습니다.\n\n" + manifest.release_notes + "\n\n지금 업데이트할까요?",
                "LAKIS 업데이트", MessageBoxButtons.YesNo, MessageBoxIcon.Information) != DialogResult.Yes) return;
            await Task.Run(() => ApplyUpdate(manifest));
            if (!String.IsNullOrWhiteSpace(pendingSelfUpdate))
            {
                status.Text = "업데이트 적용을 완료하고 있습니다…";
                string arguments = "--finish-self-update \"" + targetRoot + "\" \"" + manifest.version + "\" " + Process.GetCurrentProcess().Id;
                if (launchAfterUpdate) arguments += " --launch-after-update";
                Process.Start(new ProcessStartInfo(pendingSelfUpdate, arguments) { UseShellExecute = true, WorkingDirectory = Path.GetTempPath() });
                Close();
                return;
            }
            status.Text = "업데이트 완료 (v" + manifest.version + ")"; progress.Value = 100;
            MessageBox.Show("업데이트가 완료되었습니다.", "LAKIS 업데이트", MessageBoxButtons.OK, MessageBoxIcon.Information);
            if (launchAfterUpdate)
            {
                Process.Start(Path.Combine(targetRoot, "LAKIS.exe"));
                Close();
            }
        }
        catch (Exception error)
        {
            status.Text = "업데이트 실패";
            MessageBox.Show(error.Message, "LAKIS 업데이트 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally { update.Enabled = true; }
    }

    private UpdateManifest DownloadManifest()
    {
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
        Exception last = null;
        foreach (string url in ManifestUrls)
        {
            try
            {
                var request = (HttpWebRequest)WebRequest.Create(url + "?t=" + DateTimeOffset.UtcNow.ToUnixTimeSeconds());
                request.UserAgent = "LAKIS-Updater/7.1.4";
                request.Timeout = 20000;
                request.ReadWriteTimeout = 20000;
                request.AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate;
                request.CachePolicy = new System.Net.Cache.RequestCachePolicy(System.Net.Cache.RequestCacheLevel.NoCacheNoStore);
                string json;
                using (var response = request.GetResponse())
                using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8, true)) json = reader.ReadToEnd();
                var manifest = new JavaScriptSerializer().Deserialize<UpdateManifest>(json);
                if (manifest == null || String.IsNullOrWhiteSpace(manifest.version)) throw new InvalidDataException("업데이트 명세가 올바르지 않습니다.");
                if (manifest.files == null) manifest.files = new List<UpdateFile>();
                if (manifest.delete == null) manifest.delete = new List<string>();
                return manifest;
            }
            catch (Exception error) { last = error; }
        }
        throw new WebException("모든 업데이트 서버 연결에 실패했습니다.", last);
    }

    private void ApplyUpdate(UpdateManifest manifest)
    {
        string work = Path.Combine(Path.GetTempPath(), "LAKIS_Update_" + Guid.NewGuid().ToString("N"));
        string stage = Path.Combine(work, "stage");
        string backup = Path.Combine(targetRoot, ".lakis", "rollback", manifest.version + "_" + DateTime.Now.ToString("yyyyMMdd_HHmmss"));
        Directory.CreateDirectory(stage); Directory.CreateDirectory(backup);
        var replaced = new List<string>();
        var originallyExisted = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        try
        {
            for (int index = 0; index < manifest.files.Count; index++)
            {
                UpdateFile item = manifest.files[index];
                string relative = ValidateRelativePath(item.path);
                SetStatus("다운로드 중: " + relative, index, manifest.files.Count * 2);
                string staged = SafeCombine(stage, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(staged));
                DownloadFile(item.url, staged);
                if (!HashEquals(staged, item.sha256)) throw new InvalidDataException("파일 검증 실패: " + relative);
            }
            StopInstalledProcesses();
            for (int index = 0; index < manifest.files.Count; index++)
            {
                string relative = ValidateRelativePath(manifest.files[index].path);
                SetStatus("적용 중: " + relative, manifest.files.Count + index, manifest.files.Count * 2);
                string destination = SafeCombine(targetRoot, relative);
                string staged = SafeCombine(stage, relative);
                if (File.Exists(destination))
                {
                    originallyExisted.Add(relative);
                    string saved = SafeCombine(backup, relative);
                    Directory.CreateDirectory(Path.GetDirectoryName(saved));
                    File.Copy(destination, saved, true);
                }
                Directory.CreateDirectory(Path.GetDirectoryName(destination));
                if (String.Equals(Path.GetFullPath(destination), Path.GetFullPath(Application.ExecutablePath), StringComparison.OrdinalIgnoreCase))
                {
                    pendingSelfUpdate = Path.Combine(Path.GetTempPath(), "LAKIS_Patcher_" + Guid.NewGuid().ToString("N") + ".exe");
                    File.Copy(staged, pendingSelfUpdate, true);
                    replaced.Add(relative);
                    continue;
                }
                File.Copy(staged, destination, true);
                replaced.Add(relative);
            }
            foreach (string value in manifest.delete)
            {
                string relative = ValidateRelativePath(value);
                if (IsProtected(relative)) throw new InvalidDataException("보호된 사용자 경로는 삭제할 수 없습니다: " + relative);
                string destination = SafeCombine(targetRoot, relative);
                if (!File.Exists(destination)) continue;
                string saved = SafeCombine(backup, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(saved));
                File.Copy(destination, saved, true);
                File.Delete(destination);
            }
            CreateOrRepairDesktopShortcut(targetRoot);
            if (String.IsNullOrWhiteSpace(pendingSelfUpdate)) File.WriteAllText(Path.Combine(targetRoot, "VERSION"), manifest.version);
        }
        catch
        {
            RestoreTree(backup, targetRoot);
            foreach (string relative in replaced)
            {
                string destination = SafeCombine(targetRoot, relative);
                if (!originallyExisted.Contains(relative) && File.Exists(destination)) File.Delete(destination);
            }
            throw;
        }
        finally { try { Directory.Delete(work, true); } catch { } }
    }

    private static string ValidateRelativePath(string path)
    {
        if (String.IsNullOrWhiteSpace(path) || Path.IsPathRooted(path)) throw new InvalidDataException("잘못된 업데이트 경로입니다.");
        string normalized = path.Replace('/', Path.DirectorySeparatorChar);
        if (normalized.Split(Path.DirectorySeparatorChar).Length == 0 || normalized.Contains("..")) throw new InvalidDataException("안전하지 않은 업데이트 경로입니다: " + path);
        if (IsProtected(normalized)) throw new InvalidDataException("사용자 데이터 경로는 업데이트할 수 없습니다: " + path);
        return normalized;
    }

    private static void CreateOrRepairDesktopShortcut(string root)
    {
        string desktopHost = Path.Combine(root, "LAKIS_Desktop.exe");
        if (!File.Exists(desktopHost)) return;
        string shortcutPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "LAKIS.lnk");
        Type shellType = Type.GetTypeFromProgID("WScript.Shell");
        if (shellType == null) return;
        object shell = null;
        object shortcut = null;
        try
        {
            shell = Activator.CreateInstance(shellType);
            shortcut = shellType.InvokeMember("CreateShortcut", System.Reflection.BindingFlags.InvokeMethod,
                null, shell, new object[] { shortcutPath });
            Type shortcutType = shortcut.GetType();
            shortcutType.InvokeMember("TargetPath", System.Reflection.BindingFlags.SetProperty,
                null, shortcut, new object[] { desktopHost });
            shortcutType.InvokeMember("WorkingDirectory", System.Reflection.BindingFlags.SetProperty,
                null, shortcut, new object[] { root });
            shortcutType.InvokeMember("IconLocation", System.Reflection.BindingFlags.SetProperty,
                null, shortcut, new object[] { desktopHost + ",0" });
            shortcutType.InvokeMember("Description", System.Reflection.BindingFlags.SetProperty,
                null, shortcut, new object[] { "LAKIS Studio 실행" });
            shortcutType.InvokeMember("Save", System.Reflection.BindingFlags.InvokeMethod, null, shortcut, null);
        }
        finally
        {
            if (shortcut != null && System.Runtime.InteropServices.Marshal.IsComObject(shortcut))
                System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shortcut);
            if (shell != null && System.Runtime.InteropServices.Marshal.IsComObject(shell))
                System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
        }
    }

    private static bool IsProtected(string path)
    {
        string p = path.Replace('/', '\\').TrimStart('\\').ToLowerInvariant();
        return p.StartsWith("comfyui\\user\\") || p.StartsWith("comfyui\\output\\") || p.StartsWith("comfyui\\input\\") || p.StartsWith("comfyui\\models\\");
    }

    private static string SafeCombine(string root, string relative)
    {
        string prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        string result = Path.GetFullPath(Path.Combine(root, relative));
        if (!result.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("설치 경로 밖의 파일은 변경할 수 없습니다.");
        return result;
    }

    private static void DownloadFile(string url, string output)
    {
        using (var client = new WebClient())
        {
            client.Headers.Add(HttpRequestHeader.UserAgent, "LAKIS-Updater/7.1.4");
            client.DownloadFile(url, output);
        }
    }

    private static void RestoreTree(string source, string destinationRoot)
    {
        if (!Directory.Exists(source)) return;
        foreach (string file in Directory.GetFiles(source, "*", SearchOption.AllDirectories))
        {
            string relative = file.Substring(source.Length).TrimStart(Path.DirectorySeparatorChar);
            string output = SafeCombine(destinationRoot, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(output));
            File.Copy(file, output, true);
        }
    }

    private static bool HashEquals(string path, string expected)
    {
        if (String.IsNullOrWhiteSpace(expected) || expected.Length != 64) return false;
        using (var stream = File.OpenRead(path)) using (var sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").Equals(expected, StringComparison.OrdinalIgnoreCase);
    }

    private string ReadCurrentVersion()
    {
        string path = Path.Combine(targetRoot, "VERSION");
        return File.Exists(path) ? File.ReadAllText(path).Trim() : "0.0.0";
    }

    private static int CompareVersions(string left, string right)
    {
        Version a, b;
        if (!Version.TryParse(left, out a) || !Version.TryParse(right, out b)) return String.Compare(left, right, StringComparison.OrdinalIgnoreCase);
        return a.CompareTo(b);
    }

    private void StopInstalledProcesses()
    {
        string prefix = targetRoot.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        foreach (Process process in Process.GetProcesses())
        {
            try { if (process.Id != Process.GetCurrentProcess().Id && process.MainModule.FileName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) { process.Kill(); process.WaitForExit(5000); } }
            catch { }
            finally { process.Dispose(); }
        }
    }

    private void SetStatus(string text, int current, int total)
    {
        BeginInvoke((Action)(() => { status.Text = text; progress.Value = total > 0 ? Math.Min(100, current * 100 / total) : 0; }));
    }

    [STAThread]
    private static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        if (args.Length >= 4 && args[0] == "--finish-self-update")
        {
            FinishSelfUpdate(args);
            return;
        }
        string executableRoot = AppDomain.CurrentDomain.BaseDirectory;
        string installedRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "LAKIS");
        bool launchAfterUpdate = Array.Exists(args, value => value == "--launch-after-update");
        string root = null;
        foreach (string value in args) if (!value.StartsWith("--")) { root = value; break; }
        if (String.IsNullOrWhiteSpace(root))
            root = File.Exists(Path.Combine(executableRoot, "VERSION")) ? executableRoot : installedRoot;
        Application.Run(new UpdaterForm(root, launchAfterUpdate));
    }

    private static void FinishSelfUpdate(string[] args)
    {
        string root = Path.GetFullPath(args[1]);
        string version = args[2];
        int oldProcessId;
        Int32.TryParse(args[3], out oldProcessId);
        bool launch = Array.Exists(args, value => value == "--launch-after-update");
        try
        {
            if (oldProcessId > 0) try { Process.GetProcessById(oldProcessId).WaitForExit(15000); } catch { }
            string destination = Path.Combine(root, "LAKIS_Patcher.exe");
            Exception last = null;
            for (int attempt = 0; attempt < 10; attempt++)
            {
                try { File.Copy(Application.ExecutablePath, destination, true); last = null; break; }
                catch (Exception error) { last = error; System.Threading.Thread.Sleep(500); }
            }
            if (last != null) throw last;
            File.WriteAllText(Path.Combine(root, "VERSION"), version);
            CreateOrRepairDesktopShortcut(root);
            if (launch) Process.Start(Path.Combine(root, "LAKIS.exe"));
        }
        catch (Exception error)
        {
            MessageBox.Show("업데이트 마무리에 실패했습니다.\n\n" + error.Message, "LAKIS 업데이트 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
