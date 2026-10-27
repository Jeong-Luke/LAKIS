using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Reflection;
using System.Linq;
using System.Text.RegularExpressions;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal sealed class UpdaterForm : Form
{
    private static readonly string[] ManifestUrls = UpdateProtocol.ManifestUrls;
    private const string RcReleaseBaseVariable = "LAKIS_RC_RELEASE_BASE_URL";
    private const string RcManifestVariable = "LAKIS_RC_MANIFEST_URL";
    private const string RcRuntimeManifestVariable = "LAKIS_RC_RUNTIME_MANIFEST_URL";
    private readonly Label status = new Label();
    private readonly Label copyright;
    private readonly LakisProgressBar progress = new LakisProgressBar();
    private readonly Button update = new Button();
    private readonly string targetRoot;
    private readonly bool launchAfterUpdate;
    private readonly RuntimeHandoff runtimeHandoff;
    private readonly bool recoverRuntime;
    private readonly bool continueRuntime;
    private bool runtimeBusy;
    private string pendingSelfUpdate;
    private bool started;
    private readonly CenterCropPictureBox artwork = new CenterCropPictureBox();
    private readonly List<Image> artworkFrames = new List<Image>();
    private readonly Timer artworkTimer = new Timer();
    private int artworkIndex;
    private readonly Button closeButton = new Button();

    internal UpdaterForm(string root, bool launchWhenFinished = false)
        : this(root, launchWhenFinished, null, false) { }

    internal UpdaterForm(string root, bool launchWhenFinished, RuntimeHandoff handoff, bool recover,
        bool continueRuntimeUpdate = false)
    {
        targetRoot = Path.GetFullPath(root);
        launchAfterUpdate = launchWhenFinished;
        runtimeHandoff = handoff;
        recoverRuntime = recover;
        continueRuntime = continueRuntimeUpdate;
        Text = "LAKIS 업데이트";
        ClientSize = new Size(760, 430); FormBorderStyle = FormBorderStyle.None;
        MaximizeBox = false; StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(12, 14, 22); ForeColor = Color.White;
        Font = new Font("Segoe UI", 10F); DoubleBuffered = true;
        LakisWindowDrag.Enable(this);
        LoadArtwork();
        artwork.SetBounds(400, 48, 336, 358);
        artwork.BackColor = Color.FromArgb(18, 22, 38);
        if (artworkFrames.Count > 0) artwork.Image = artworkFrames[0];
        artworkTimer.Interval = 5000;
        artworkTimer.Tick += (_, __) => {
            if (artworkFrames.Count < 2) return;
            artworkIndex = (artworkIndex + 1) % artworkFrames.Count;
            artwork.Image = artworkFrames[artworkIndex];
        };
        artworkTimer.Start();
        var logo = new PictureBox {
            Left = 42, Top = 42, Width = 54, Height = 54,
            SizeMode = PictureBoxSizeMode.Zoom,
            Image = Icon.ExtractAssociatedIcon(Application.ExecutablePath).ToBitmap()
        };
        Controls.Add(new Label {
            Left = 112, Top = 43, Width = 280, Height = 34, Text = "L A K I S",
            Font = new Font("Segoe UI", 20F, FontStyle.Bold), ForeColor = Color.FromArgb(225, 229, 255)
        });
        Controls.Add(new Label {
            Left = 114, Top = 78, Width = 260, Height = 25, Text = "Studio",
            Font = new Font("Segoe UI", 11F, FontStyle.Bold), ForeColor = Color.FromArgb(171, 178, 203)
        });
        Controls.Add(new Label {
            Left = 43, Top = 217, Width = 315, Height = 46,
            Text = "안전한 업데이트를 확인하고 적용합니다.",
            ForeColor = Color.FromArgb(104, 112, 137), Font = new Font("Segoe UI", 8F)
        });
        copyright = new Label {
            Left = 43, Top = 399, Width = 335, Height = 18,
            ForeColor = Color.FromArgb(104, 112, 137), Font = new Font("Segoe UI", 8F)
        };
        RefreshInstalledVersion();
        status.Left = 43; status.Top = 277; status.Width = 315; status.Height = 34;
        status.Text = "업데이트 확인 준비 완료"; status.ForeColor = Color.FromArgb(184, 168, 255);
        progress.Left = 43; progress.Top = 318; progress.Width = 315; progress.Height = 7;
        update.Left = 238; update.Top = 350; update.Width = 120; update.Height = 38; update.Text = "확인";
        update.FlatStyle = FlatStyle.Flat; update.FlatAppearance.BorderSize = 0;
        update.BackColor = Color.FromArgb(111, 82, 225); update.ForeColor = Color.White;
        update.Font = new Font("Segoe UI", 10F, FontStyle.Bold); update.Cursor = Cursors.Hand;
        update.Visible = false;
        ConfigureCloseButton();
        Controls.AddRange(new Control[] { artwork, logo, status, progress, update, copyright, closeButton });
        closeButton.BringToFront();
        Shown += async (_, __) => {
            if (started) return;
            started = true;
            await UpdateAsync();
        };
        FormClosed += (_, __) => { artworkTimer.Stop(); foreach (Image frame in artworkFrames) frame.Dispose(); };
        FormClosing += (_, args) => { if (runtimeBusy) args.Cancel = true; };
    }

    private void ConfigureCloseButton()
    {
        closeButton.SetBounds(ClientSize.Width - 48, 0, 48, 42);
        closeButton.Text = "\uE8BB";
        closeButton.Font = new Font("Segoe MDL2 Assets", 9F);
        closeButton.ForeColor = Color.FromArgb(205, 211, 225);
        closeButton.BackColor = Color.Transparent;
        closeButton.FlatStyle = FlatStyle.Flat;
        closeButton.FlatAppearance.BorderSize = 0;
        closeButton.FlatAppearance.MouseOverBackColor = Color.FromArgb(196, 43, 28);
        closeButton.TabStop = false;
        closeButton.Cursor = Cursors.Hand;
        closeButton.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        closeButton.Click += (_, __) => Close();
    }

    private void LoadArtwork()
    {
        Assembly assembly = Assembly.GetExecutingAssembly();
        foreach (string name in new[] { "LAKIS.Splash1", "LAKIS.Splash2" })
        {
            using (Stream stream = assembly.GetManifestResourceStream(name))
                if (stream != null) artworkFrames.Add(new Bitmap(stream));
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        using (var border = new Pen(Color.FromArgb(47, 54, 73)))
            e.Graphics.DrawRectangle(border, 0, 0, ClientSize.Width - 1, ClientSize.Height - 1);
    }

    private async Task UpdateAsync()
    {
        update.Enabled = false; progress.Value = 0;
        progress.Style = ProgressBarStyle.Marquee; progress.MarqueeAnimationSpeed = 24;
        try
        {
            if (!recoverRuntime) UpdateProtocol.EnsureNoPendingRuntimeTransition(targetRoot);
            if (recoverRuntime)
            {
                if (MessageBox.Show("이 업데이트 이전의 프로그램과 DB로 복구할까요?\n생성 이미지와 백업은 보존됩니다.",
                    "LAKIS 업데이트 복구", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
                runtimeBusy = true;
                await Task.Run(() => RuntimeBundleInstaller.Apply(runtimeHandoff, ReportRuntimeProgress, true));
                runtimeBusy = false;
                RefreshInstalledVersion();
                status.Text = "이전 버전 복구 완료"; progress.Value = 100;
                return;
            }
            if (!File.Exists(Path.Combine(targetRoot, "LAKIS.exe")) || !Directory.Exists(Path.Combine(targetRoot, "ComfyUI")))
                throw new DirectoryNotFoundException("LAKIS 설치 위치를 찾을 수 없습니다: " + targetRoot);
            status.Text = "업데이트 정보를 확인하고 있습니다…";
            UpdateManifest manifest = runtimeHandoff == null
                ? await Task.Run(() => DownloadManifest())
                : UpdateProtocol.Read(File.ReadAllText(Path.Combine(runtimeHandoff.workspace, "manifest.json")));
            UpdateProtocol.ValidateForInstallation(manifest, ReadCurrentVersion());
            if (continueRuntime)
                UpdateProtocol.ValidateRuntimeContinuation(manifest, ReadCurrentVersion());
            progress.Style = ProgressBarStyle.Continuous; progress.Value = 0;
            string current = ReadCurrentVersion();
            if (CompareVersions(manifest.version, current) <= 0)
            {
                status.Text = "최신 버전입니다. (v" + current + ")";
                MessageBox.Show("현재 LAKIS가 최신 버전입니다.", "LAKIS 업데이트", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            if (runtimeHandoff == null && !launchAfterUpdate && !continueRuntime && MessageBox.Show(
                "v" + manifest.version + " 업데이트가 있습니다.\n\n" + manifest.release_notes + "\n\n지금 업데이트할까요?",
                "LAKIS 업데이트", MessageBoxButtons.YesNo, MessageBoxIcon.Information) != DialogResult.Yes) return;
            if (manifest.kind == "runtime-update")
            {
                runtimeBusy = true;
                if (runtimeHandoff != null)
                    await Task.Run(() => RuntimeBundleInstaller.Apply(runtimeHandoff, ReportRuntimeProgress));
                else
                {
                    var prepared = await Task.Run(() => PrepareRuntimeUpdate(manifest));
                    string helper = Path.Combine(prepared.workspace, "LAKIS_Updater.exe");
                    CopyVerifiedFile(Application.ExecutablePath, helper,
                        RuntimeBundleInstaller.HashFile(Application.ExecutablePath));
                    string handoffPath = RuntimeBundleInstaller.WriteHandoff(prepared, launchAfterUpdate);
                    var helperInfo = new ProcessStartInfo(helper, "--finish-runtime-transition " +
                        RuntimeBundleInstaller.Quote(handoffPath) + " " +
                        RuntimeBundleInstaller.Quote(RuntimeBundleInstaller.HashFile(handoffPath))) {
                        UseShellExecute = false, WorkingDirectory = prepared.workspace
                    };
                    CopyRcEnvironment(helperInfo);
                    Process.Start(helperInfo);
                    runtimeBusy = false;
                    Close();
                    return;
                }
                runtimeBusy = false;
            }
            else await Task.Run(() => ApplyUpdate(manifest));
            RefreshInstalledVersion();
            if (!String.IsNullOrWhiteSpace(pendingSelfUpdate))
            {
                status.Text = "업데이트 적용을 완료하고 있습니다…";
                string arguments = "--finish-self-update \"" + targetRoot + "\" \"" + manifest.version + "\" " + Process.GetCurrentProcess().Id;
                arguments += " --self-name=" + Path.GetFileName(Application.ExecutablePath);
                if (launchAfterUpdate) arguments += " --launch-after-update";
                var helperInfo = new ProcessStartInfo(pendingSelfUpdate, arguments) { UseShellExecute = false, WorkingDirectory = Path.GetTempPath() };
                CopyRcEnvironment(helperInfo);
                Process.Start(helperInfo);
                Close();
                return;
            }
            status.Text = "업데이트 완료 (v" + manifest.version + ")"; progress.Value = 100;
            MessageBox.Show("업데이트가 완료되었습니다.", "LAKIS 업데이트", MessageBoxButtons.OK, MessageBoxIcon.Information);
            if (launchAfterUpdate)
            {
                var launcherInfo = new ProcessStartInfo(Path.Combine(targetRoot, "LAKIS.exe"))
                {
                    UseShellExecute = false,
                    WorkingDirectory = targetRoot
                };
                CopyRcEnvironment(launcherInfo);
                Process.Start(launcherInfo);
                Close();
            }
        }
        catch (Exception error)
        {
            status.Text = "업데이트 실패";
            MessageBox.Show(error.Message, "LAKIS 업데이트 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally { runtimeBusy = false; progress.Style = ProgressBarStyle.Continuous; update.Enabled = true; }
    }

    private RuntimeHandoff PrepareRuntimeUpdate(UpdateManifest manifest)
    {
        UpdateProtocol.EnsureNoPendingRuntimeTransition(targetRoot);
        UpdateProtocol.ValidateForInstallation(manifest, ReadCurrentVersion());
        StopInstalledProcesses();
        string cache = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "LAKIS", "installer-cache");
        return RuntimeBundleInstaller.Prepare(Path.Combine(targetRoot, "python_embeded", "python.exe"),
            new JavaScriptSerializer().Serialize(manifest), targetRoot, cache, ReportRuntimeProgress);
    }

    private void ReportRuntimeProgress(string line)
    {
        if (String.IsNullOrWhiteSpace(line) || line.StartsWith("{")) return;
        var count = Regex.Match(line, @"(\d[\d,]*)/(\d[\d,]*)\s*$");
        long current, total;
        if (count.Success && Int64.TryParse(count.Groups[1].Value.Replace(",", ""), out current) &&
            Int64.TryParse(count.Groups[2].Value.Replace(",", ""), out total) && total > 0)
            SetStatus(line, (int)Math.Min(100, current * 100 / total), 100);
        else SetStatus(line, 0, 0);
    }

    private UpdateManifest DownloadManifest()
    {
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
        Exception last = null;
        foreach (string url in EffectiveManifestUrls())
        {
            try
            {
                var request = (HttpWebRequest)WebRequest.Create(url + "?t=" + DateTimeOffset.UtcNow.ToUnixTimeSeconds());
                request.UserAgent = "LAKIS-Updater/" + UpdateProtocol.EngineVersion;
                request.Timeout = 20000;
                request.ReadWriteTimeout = 20000;
                request.AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate;
                request.CachePolicy = new System.Net.Cache.RequestCachePolicy(System.Net.Cache.RequestCacheLevel.NoCacheNoStore);
                string json;
                using (var response = request.GetResponse())
                {
                    ValidateDownloadOrigin(url, response.ResponseUri.AbsoluteUri);
                    using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8, true)) json = reader.ReadToEnd();
                }
                var manifest = UpdateProtocol.Read(json);
                UpdateProtocol.ValidateForInstallation(manifest, ReadCurrentVersion());
                return manifest;
            }
            catch (InvalidDataException) { throw; }
            catch (Exception error) { last = error; }
        }
        throw new WebException("모든 업데이트 서버 연결에 실패했습니다.", last);
    }

    private static string ValidateRcLoopbackUrl(string value, string variable)
    {
        Uri uri;
        if (!Uri.TryCreate(value, UriKind.Absolute, out uri) ||
            !String.Equals(uri.Scheme, Uri.UriSchemeHttp, StringComparison.OrdinalIgnoreCase) ||
            !Regex.IsMatch(uri.Authority, "^(127\\.0\\.0\\.1|localhost):[0-9]+$", RegexOptions.IgnoreCase) ||
            !String.IsNullOrEmpty(uri.UserInfo) || !String.IsNullOrEmpty(uri.Fragment) ||
            !String.IsNullOrEmpty(uri.Query) || uri.Port < 1 || value.IndexOf('\\') >= 0 ||
            Regex.IsMatch(value, "(^|/)\\.{1,2}(/|$)|%2e|%2f|%5c", RegexOptions.IgnoreCase))
            throw new InvalidDataException(variable + " must be an http loopback URL (127.0.0.1 or localhost) with an explicit port.");
        string decodedPath;
        try { decodedPath = Uri.UnescapeDataString(uri.AbsolutePath); }
        catch (UriFormatException) { throw new InvalidDataException(variable + " contains malformed escaping."); }
        if (decodedPath.Replace('\\', '/').Split('/').Any(part => part == "." || part == ".."))
            throw new InvalidDataException(variable + " must not contain path traversal.");
        return uri.AbsoluteUri.TrimEnd('/');
    }

    private static IEnumerable<string> EffectiveManifestUrls()
    {
        string overrideUrl = Environment.GetEnvironmentVariable(RcManifestVariable);
        if (String.IsNullOrWhiteSpace(overrideUrl)) return ManifestUrls;
        return new[] { ValidateRcLoopbackUrl(overrideUrl, RcManifestVariable) };
    }

    private static void CopyRcEnvironment(ProcessStartInfo info)
    {
        foreach (string name in new[] { RcReleaseBaseVariable, RcManifestVariable, RcRuntimeManifestVariable })
        {
            string value = Environment.GetEnvironmentVariable(name);
            if (!String.IsNullOrWhiteSpace(value)) info.EnvironmentVariables[name] = value;
        }
    }

    internal static ProcessStartInfo CreateRuntimeContinuation(string root, bool launch)
    {
        RuntimeBundleInstaller.VerifyCandidateEngine(root);
        var info = new ProcessStartInfo(Path.Combine(root, "LAKIS_Updater.exe"),
            RuntimeBundleInstaller.Quote(root) + " --continue-runtime-update" +
            (launch ? " --launch-after-update" : "")) {
            UseShellExecute = false, WorkingDirectory = root
        };
        CopyRcEnvironment(info);
        string bridgeUrl = Environment.GetEnvironmentVariable(RcManifestVariable);
        string runtimeUrl = Environment.GetEnvironmentVariable(RcRuntimeManifestVariable);
        if (!String.IsNullOrWhiteSpace(bridgeUrl) || !String.IsNullOrWhiteSpace(runtimeUrl))
        {
            // An isolated RC must never fall back to the public channel or
            // fetch its bootstrap manifest again after replacing the engine.
            ValidateRcLoopbackUrl(bridgeUrl, RcManifestVariable);
            info.EnvironmentVariables[RcManifestVariable] =
                ValidateRcLoopbackUrl(runtimeUrl, RcRuntimeManifestVariable);
        }
        return info;
    }

    private void ApplyUpdate(UpdateManifest manifest)
    {
        UpdateProtocol.EnsureNoPendingRuntimeTransition(targetRoot);
        UpdateProtocol.ValidateForInstallation(manifest, ReadCurrentVersion());
        if (manifest.kind != "file-patch")
            throw new InvalidDataException("런타임 교체는 전용 엔진으로만 실행할 수 있습니다.");
        string work = Path.Combine(Path.GetTempPath(), "LAKIS_Update_" + Guid.NewGuid().ToString("N"));
        string stage = Path.Combine(work, "stage");
        string backup = SafeCombine(targetRoot, Path.Combine(".lakis", "rollback", manifest.version + "_" + DateTime.Now.ToString("yyyyMMdd_HHmmss")));
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
                DownloadVerifiedFile(item.url, staged, item.sha256, relative);
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
                    CopyVerifiedFile(staged, pendingSelfUpdate, manifest.files[index].sha256);
                    replaced.Add(relative);
                    continue;
                }
                replaced.Add(relative);
                CopyVerifiedFile(staged, destination, manifest.files[index].sha256);
            }
            foreach (string value in manifest.delete)
            {
                string relative = ValidateDeleteRelativePath(value);
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
            if(!String.IsNullOrWhiteSpace(pendingSelfUpdate))
                try { File.Delete(pendingSelfUpdate); } catch { }
            throw;
        }
        finally { try { Directory.Delete(work, true); } catch { } }
    }

    private static string ValidateRelativePath(string path)
    {
        string normalized = ValidatePathSyntax(path);
        string p = normalized.Replace('\\', '/');
        var rootFiles = new[] {"LAKIS.exe", "LAKIS_Patcher.exe", "LAKIS_Updater.exe", "LAKIS_Desktop.exe", "LAKIS_Model_Importer.exe", "Uninstall_LAKIS.exe", "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll", "LICENSE.md", "THIRD_PARTY_NOTICES.md"};
        var packages = new[] {"ComfyUI-Anima-LLLite", "ComfyUI-KR-Camera-Control", "ComfyUI-KR-Camera-PromptStudio-Bridge", "ComfyUI-LAKIS-AutoPatch", "ComfyUI-LAKIS-Detail", "ComfyUI-LAKIS-Fast-Refiner", "ComfyUI-LAKIS-Local-Inpaint", "ComfyUI-PreviewMonitor"};
        bool owned = rootFiles.Any(name => String.Equals(p, name, StringComparison.OrdinalIgnoreCase)) ||
            p.StartsWith("third_party_licenses/", StringComparison.OrdinalIgnoreCase) ||
            p.StartsWith("ComfyUI/LAKIS/external_ui/", StringComparison.OrdinalIgnoreCase) ||
            String.Equals(p, "ComfyUI/LAKIS/STOP_AUTOMATION", StringComparison.OrdinalIgnoreCase) ||
            String.Equals(p, "ComfyUI/LAKIS/sync_runtime_workflow.py", StringComparison.OrdinalIgnoreCase) ||
            String.Equals(p, "ComfyUI/LAKIS/workflows/LAKIS_runtime_api_v7.4.json", StringComparison.OrdinalIgnoreCase) ||
            String.Equals(p, "ComfyUI/LAKIS/workflows/LAKIS_runtime_visual_v7.4.json", StringComparison.OrdinalIgnoreCase) ||
            packages.Any(name => p.StartsWith("ComfyUI/custom_nodes/" + name + "/", StringComparison.OrdinalIgnoreCase) && !p.EndsWith("/startup_workflow.json", StringComparison.OrdinalIgnoreCase));
        if (!owned) throw new InvalidDataException("배포 관리 파일만 업데이트할 수 있습니다: " + path);
        return normalized;
    }

    private static string ValidateDeleteRelativePath(string path)
    {
        string normalized = ValidatePathSyntax(path);
        string p = normalized.Replace('\\', '/');
        var retired = new[] {"ComfyUI/LAKIS/external_ui/light-control-prototype.css", "ComfyUI/LAKIS/external_ui/lightmap-knob-mockup.js", "ComfyUI/LAKIS/workflows/LAKIS_DETAIL_runtime_api_v7.3.json", "ComfyUI/LAKIS/workflows/LAKIS_runtime_api_v7.1.json", "ComfyUI/LAKIS/workflows/LAKIS_runtime_visual_v7.3.json", "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/INSTALL_REQUIREMENTS.bat", "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/LICENSE", "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/NOTICE.md", "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/__init__.py", "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/requirements.txt", "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/web/lakis_light_control.js"};
        if (!retired.Any(name => String.Equals(p, name, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidDataException("지정된 폐기 파일만 삭제할 수 있습니다: " + path);
        return normalized;
    }

    private static string ValidatePathSyntax(string path)
    {
        if (String.IsNullOrWhiteSpace(path) || Path.IsPathRooted(path)) throw new InvalidDataException("잘못된 업데이트 경로입니다.");
        string normalized = path.Replace('/', Path.DirectorySeparatorChar);
        foreach (string part in normalized.Split(Path.DirectorySeparatorChar))
            if (String.IsNullOrEmpty(part) || part == "." || part == ".." || part.EndsWith(".") || part.EndsWith(" ") ||
                part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
                System.Text.RegularExpressions.Regex.IsMatch(part, "^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\\.|$)", System.Text.RegularExpressions.RegexOptions.IgnoreCase))
                throw new InvalidDataException("안전하지 않은 업데이트 경로입니다: " + path);
        if (IsProtected(normalized)) throw new InvalidDataException("사용자 데이터 경로는 업데이트할 수 없습니다: " + path);
        return normalized;
    }

    private static void CreateOrRepairDesktopShortcut(string root)
    {
        string desktopHost = Path.Combine(root, "LAKIS_Desktop.exe");
        string iconPath = Path.Combine(root, "LAKIS.ico");
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
                null, shortcut, new object[] { (File.Exists(iconPath) ? iconPath : desktopHost) + ",0" });
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
        for (string current = result; !String.IsNullOrEmpty(current); current = Path.GetDirectoryName(current))
        {
            try { if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)throw new InvalidDataException("연결된 경로에는 업데이트할 수 없습니다: " + relative); }
            catch (FileNotFoundException) { }
            catch (DirectoryNotFoundException) { }
        }
        return result;
    }

    private static void DownloadVerifiedFile(string url, string output, string expectedHash, string relativePath)
    {
        Exception last = null;
        for (int attempt = 1; attempt <= 3; attempt++)
        {
            try
            {
                if (File.Exists(output)) File.Delete(output);
                string separator = url.Contains("?") ? "&" : "?";
                string requestUrl = url + separator + "lakis_update=" + DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + "_" + attempt;
                using (var client = new ApprovedDownloadClient())
                {
                    client.Headers.Add(HttpRequestHeader.UserAgent, "LAKIS-Updater/7.4.5");
                    client.Headers.Add(HttpRequestHeader.CacheControl, "no-cache, no-store, must-revalidate");
                    client.DownloadFile(requestUrl, output);
                }
                if (HashEquals(output, expectedHash)) return;
                last = new InvalidDataException("SHA-256 mismatch on attempt " + attempt);
            }
            catch (Exception error) { last = error; }
        }
        if (File.Exists(output)) File.Delete(output);
        throw new InvalidDataException("파일 검증 실패(3회 재시도): " + relativePath, last);
    }
    private sealed class ApprovedDownloadClient : WebClient
    {
        protected override WebRequest GetWebRequest(Uri address)
        {
            ValidateDownloadOrigin(address.AbsoluteUri,address.AbsoluteUri);
            return base.GetWebRequest(address);
        }
        protected override WebResponse GetWebResponse(WebRequest request)
        {
            var response=base.GetWebResponse(request);
            try { ValidateDownloadOrigin(request.RequestUri.AbsoluteUri,response.ResponseUri.AbsoluteUri);return response; }
            catch {response.Close();throw;}
        }
    }
    private static void ValidateDownloadOrigin(string requested,string final)
    {
        var original=new Uri(requested,UriKind.Absolute);
        bool localRequest=original.Scheme=="http"&&original.IsLoopback;
        foreach(string value in new[]{requested,final})
        {
            var uri=new Uri(value,UriKind.Absolute);
            string host=uri.DnsSafeHost.ToLowerInvariant();
            string[] hosts={"github.com","api.github.com","codeload.github.com","raw.githubusercontent.com","objects.githubusercontent.com","release-assets.githubusercontent.com","cdn.jsdelivr.net","huggingface.co","go.microsoft.com","msedge.sf.dl.delivery.mp.microsoft.com"};
            bool approved=Array.Exists(hosts,h=>h==host)||host.EndsWith(".hf.co",StringComparison.Ordinal);
            bool local=localRequest&&uri.Scheme=="http"&&uri.IsLoopback&&String.Equals(uri.Authority,original.Authority,StringComparison.OrdinalIgnoreCase);
            if(!String.IsNullOrEmpty(uri.UserInfo)||!(local||(uri.Scheme=="https"&&approved)))
                throw new IOException("DOWNLOAD_ORIGIN_INVALID: unapproved download origin");
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

    private static void CopyVerifiedFile(string source, string destination, string expected)
    {
        // The same read handle verifies and supplies the bytes. FileShare.Read
        // excludes concurrent writes/replacement until the copy is complete.
        using(var input=new FileStream(source,FileMode.Open,FileAccess.Read,FileShare.Read))
        {
            using(var hash=SHA256.Create())
                if(!BitConverter.ToString(hash.ComputeHash(input)).Replace("-","").Equals(expected,StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("적용 직전 SHA-256 검증 실패: "+Path.GetFileName(source));
            input.Position=0;
            using(var output=new FileStream(destination,FileMode.Create,FileAccess.Write,FileShare.None))input.CopyTo(output);
        }
    }

    private string ReadCurrentVersion()
    {
        string path = Path.Combine(targetRoot, "VERSION");
        return File.Exists(path) ? File.ReadAllText(path).Trim() : "0.0.0";
    }

    private void RefreshInstalledVersion()
    {
        copyright.Text = "© 2026 Luke Jeong. All rights reserved. · LAKIS v" + ReadCurrentVersion();
    }

    private static int CompareVersions(string left, string right)
    {
        return UpdateProtocol.CompareVersions(left, right);
    }

    private void StopInstalledProcesses()
    {
        // A directory prefix does not prove ownership of Python/DEV/LUKIS.
        // Until exact owned-process shutdown is verified, fail closed instead
        // of terminating unrelated work. Allow a closing Launcher to exit.
        string prefix = targetRoot.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        var remaining = new List<int>();
        int ownPid = Process.GetCurrentProcess().Id;
        for (int pass = 0; pass < 6; pass++)
        {
            remaining.Clear();
            foreach (Process process in Process.GetProcesses())
            {
                try
                {
                    if (process.Id != ownPid && !process.HasExited &&
                        process.MainModule.FileName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                        remaining.Add(process.Id);
                }
                catch (System.ComponentModel.Win32Exception) { }
                catch (InvalidOperationException) { }
                finally { process.Dispose(); }
            }
            if (remaining.Count == 0) return;
            System.Threading.Thread.Sleep(500);
        }
        throw new IOException("업데이트 전에 이 설치를 사용하는 LAKIS/ComfyUI를 종료해 주세요. 다른 프로그램은 자동 종료하지 않습니다. PID: " + String.Join(",", remaining));
    }

    private void SetStatus(string text, int current, int total)
    {
        BeginInvoke((Action)(() => {
            status.Text = text;
            progress.Style = total > 0 ? ProgressBarStyle.Continuous : ProgressBarStyle.Marquee;
            progress.Value = total > 0 ? Math.Min(100, current * 100 / total) : 0;
        }));
    }

    [STAThread]
    private static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        if (args.Length == 3 && (args[0] == "--finish-runtime-transition" || args[0] == "--recover-runtime-transition"))
        {
            try
            {
                var handoff = RuntimeBundleInstaller.ReadHandoff(args[1], args[2]);
                bool recover = args[0] == "--recover-runtime-transition";
                Application.Run(new UpdaterForm(handoff.target, handoff.launch && !recover, handoff, recover));
            }
            catch (Exception error)
            {
                MessageBox.Show(error.Message, "LAKIS 업데이트 인계 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            return;
        }
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
        bool continueRuntime = Array.Exists(args, value => value == "--continue-runtime-update");
        Application.Run(new UpdaterForm(root, launchAfterUpdate, null, false, continueRuntime));
    }

    private static void FinishSelfUpdate(string[] args)
    {
        string root = Path.GetFullPath(args[1]);
        string version = args[2];
        int oldProcessId;
        Int32.TryParse(args[3], out oldProcessId);
        bool launch = Array.Exists(args, value => value == "--launch-after-update");
        string destination = null;
        string retiredExecutable = null;
        try
        {
            string selfName = null;
            foreach (string value in args)
                if (value.StartsWith("--self-name=", StringComparison.Ordinal)) selfName = value.Substring(12);

            Process oldProcess = null;
            try
            {
                string oldExecutable = null;
                if (String.IsNullOrWhiteSpace(selfName) && oldProcessId > 0)
                {
                    try
                    {
                        oldProcess = Process.GetProcessById(oldProcessId);
                        oldExecutable = Path.GetFullPath(oldProcess.MainModule.FileName);
                    }
                    catch (ArgumentException) { }
                    catch (InvalidOperationException)
                    {
                        if (oldProcess != null) oldProcess.Dispose();
                        oldProcess = null;
                    }
                    catch (System.ComponentModel.Win32Exception)
                    {
                        if (oldProcess != null) oldProcess.Dispose();
                        oldProcess = null;
                    }
                }
                if (String.IsNullOrWhiteSpace(selfName))
                {
                    string patcher = Path.GetFullPath(Path.Combine(root, "LAKIS_Patcher.exe"));
                    string updater = Path.GetFullPath(Path.Combine(root, "LAKIS_Updater.exe"));
                    if (!String.IsNullOrWhiteSpace(oldExecutable) && String.Equals(oldExecutable, patcher, StringComparison.OrdinalIgnoreCase))
                        selfName = "LAKIS_Patcher.exe";
                    else if (!String.IsNullOrWhiteSpace(oldExecutable) && String.Equals(oldExecutable, updater, StringComparison.OrdinalIgnoreCase))
                        selfName = "LAKIS_Updater.exe";
                    else if (!String.IsNullOrWhiteSpace(oldExecutable))
                        throw new InvalidDataException("Legacy updater process is not an approved executable in the installation root.");
                    else
                    {
                        string helperHash = ComputeSha256(Application.ExecutablePath);
                        bool patcherIsCandidate = File.Exists(patcher) && String.Equals(
                            ComputeSha256(patcher), helperHash, StringComparison.OrdinalIgnoreCase);
                        bool updaterIsCandidate = File.Exists(updater) && String.Equals(
                            ComputeSha256(updater), helperHash, StringComparison.OrdinalIgnoreCase);
                        if (patcherIsCandidate == updaterIsCandidate)
                            throw new InvalidDataException("Legacy updater alias cannot be determined safely from installation state.");
                        selfName = patcherIsCandidate ? "LAKIS_Updater.exe" : "LAKIS_Patcher.exe";
                    }
                }
                if (!String.Equals(selfName, "LAKIS_Patcher.exe", StringComparison.OrdinalIgnoreCase) &&
                    !String.Equals(selfName, "LAKIS_Updater.exe", StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Invalid updater self-update target.");
                destination = Path.GetFullPath(Path.Combine(root, selfName));
                if (File.Exists(destination))
                {
                    string retiredDirectory = Path.Combine(root, ".lakis", "self-update-retired");
                    Directory.CreateDirectory(retiredDirectory);
                    retiredExecutable = Path.Combine(retiredDirectory,
                        selfName + "." + Guid.NewGuid().ToString("N") + ".old");
                    File.Move(destination, retiredExecutable);
                }
                if (oldProcess != null &&
                    !String.Equals(oldExecutable, destination, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Updater process identity does not match the approved self-update target.");
            }
            finally { }
            Exception last = null;
            for (int attempt = 0; attempt < 10; attempt++)
            {
                try { File.Copy(Application.ExecutablePath, destination, true); last = null; break; }
                catch (Exception error) { last = error; System.Threading.Thread.Sleep(500); }
            }
            if (last != null) throw last;
            ProcessStartInfo continuation = version == UpdateProtocol.RuntimeBridgeVersion
                ? CreateRuntimeContinuation(root, launch) : null;
            File.WriteAllText(Path.Combine(root, "VERSION"), version);
            CreateOrRepairDesktopShortcut(root);
            if (launch && continuation == null)
            {
                var launcherInfo = new ProcessStartInfo(Path.Combine(root, "LAKIS.exe")) { UseShellExecute = false, WorkingDirectory = root };
                CopyRcEnvironment(launcherInfo);
                Process.Start(launcherInfo);
            }
            if (oldProcess != null)
            {
                try
                {
                    if (!oldProcess.WaitForExit(1000)) oldProcess.Kill();
                    oldProcess.WaitForExit(5000);
                }
                catch { }
                finally { oldProcess.Dispose(); }
            }
            if (!String.IsNullOrWhiteSpace(retiredExecutable))
                try { File.Delete(retiredExecutable); } catch { }
            if (continuation != null) Process.Start(continuation);
        }
        catch (Exception error)
        {
            if (!String.IsNullOrWhiteSpace(destination) && !File.Exists(destination) &&
                !String.IsNullOrWhiteSpace(retiredExecutable) && File.Exists(retiredExecutable))
                try { File.Move(retiredExecutable, destination); } catch { }
            MessageBox.Show("업데이트 마무리에 실패했습니다.\n\n" + error.Message, "LAKIS 업데이트 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static string ComputeSha256(string path)
    {
        using (var stream = File.OpenRead(path))
        using (var sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "");
    }
}
