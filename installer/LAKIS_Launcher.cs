using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Web.Script.Serialization;

internal static class LakisLauncher
{
#if LAKIS_LUKE
    private const bool DevelopmentBuild = false;
    private const bool PrivateLukeBuild = true;
    private const string ProductTitle = "LUKIS Studio";
    private const string DesktopMutexName = "Local\\LUKIS-Studio-Desktop";
    private const string StartupMutexName = "Local\\LUKIS-Studio-Startup";
#elif LAKIS_DEV
    private const bool DevelopmentBuild = true;
    private const bool PrivateLukeBuild = false;
    private const string ProductTitle = "LAKIS Studio DEV";
    private const string DesktopMutexName = "Local\\LAKIS-Studio-DEV-Desktop";
    private const string StartupMutexName = "Local\\LAKIS-Studio-DEV-Startup";
#else
    private const bool DevelopmentBuild = false;
    private const bool PrivateLukeBuild = false;
    private const string ProductTitle = "LAKIS Studio";
    private const string DesktopMutexName = "Local\\LAKIS-Studio-Desktop";
    private const string StartupMutexName = "Local\\LAKIS-Studio-Startup";
#endif
    private static readonly string[] ManifestUrls = {
        "https://raw.githubusercontent.com/Jeong-Luke/LAKIS/main/manifests/update-latest.json",
        "https://cdn.jsdelivr.net/gh/Jeong-Luke/LAKIS@main/manifests/update-latest.json"
    };
    private const string LatestReleaseApiUrl = "https://api.github.com/repos/Jeong-Luke/LAKIS/releases/latest";

    private sealed class ReleaseLayoutFile
    {
        public string path { get; set; }
        public long size { get; set; }
    }

    private sealed class ReleaseLayout
    {
        public int schema { get; set; }
        public string product { get; set; }
        public string version { get; set; }
        public List<ReleaseLayoutFile> files { get; set; }
        public List<string> retired { get; set; }
    }

    private sealed class StartupForm : Form
    {
        private readonly Label status = new Label();
        private readonly LakisProgressBar progress = new LakisProgressBar();
        private readonly string root;
        private Process startupProcess;
        private bool userCancelled;
        private bool startupCompleted;
        private DateTime startupProcessStartedAt;
        private readonly CenterCropPictureBox artwork = new CenterCropPictureBox();
        private readonly List<Image> artworkFrames = new List<Image>();
        private readonly System.Windows.Forms.Timer artworkTimer = new System.Windows.Forms.Timer();
        private int artworkIndex;

        internal StartupForm(string installRoot)
        {
            root = installRoot;
            Text = ProductTitle;
            ClientSize = new Size(760, 430);
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.None;
            MaximizeBox = false;
            BackColor = Color.FromArgb(12, 14, 22);
            ForeColor = Color.White;
            Font = new Font("Segoe UI", 10F);
            DoubleBuffered = true;
            MouseDown += DragWindow;

            LoadArtwork();
            artwork.SetBounds(400, 48, 336, 358);
            artwork.BackColor = Color.FromArgb(18, 22, 38);
            if (artworkFrames.Count > 0) artwork.Image = artworkFrames[0];
            artworkTimer.Interval = 5000;
            artworkTimer.Tick += (_, __) => {
                if (artworkFrames.Count < 2) return;
                artworkIndex = (artworkIndex + 1) % artworkFrames.Count;
                artwork.Image = artworkFrames[artworkIndex];
                artwork.Invalidate();
            };
            artworkTimer.Start();

            var logo = new PictureBox {
                Left = 42, Top = 42, Width = 54, Height = 54,
                SizeMode = PictureBoxSizeMode.Zoom,
                Image = Icon.ExtractAssociatedIcon(Application.ExecutablePath).ToBitmap()
            };
            var title = new Label {
                Left = 112, Top = 43, Width = 280, Height = 34,
                Text = "L A K I S", Font = new Font("Segoe UI", 20F, FontStyle.Bold),
                ForeColor = Color.FromArgb(225, 229, 255)
            };
            title.MouseDown += DragWindow;
            var subtitle = new Label {
                Left = 114, Top = 78, Width = 260, Height = 25,
                Text = PrivateLukeBuild ? "Studio · LUKE" : (DevelopmentBuild ? "Studio · DEVELOPMENT" : "Studio"), Font = new Font("Segoe UI", 11F, FontStyle.Bold),
                ForeColor = Color.FromArgb(171, 178, 203)
            };
            subtitle.MouseDown += DragWindow;
            var close = new Button {
                Left = 712, Top = 0, Width = 48, Height = 42, Text = "",
                Font = new Font("Segoe MDL2 Assets", 9F), ForeColor = Color.FromArgb(205, 211, 225),
                BackColor = Color.Transparent, FlatStyle = FlatStyle.Flat, TabStop = false,
                Cursor = Cursors.Hand
            };
            close.FlatAppearance.BorderSize = 0;
            close.FlatAppearance.MouseOverBackColor = Color.FromArgb(196, 43, 28);
            close.Click += (_, __) => CancelStartup();
            var copyright = new Label {
                Left = 43, Top = 399, Width = 335, Height = 18,
                Text = "© 2026 Luke Jeong. All rights reserved. · LAKIS " + ReadVersion(installRoot),
                ForeColor = Color.FromArgb(104, 112, 137), Font = new Font("Segoe UI", 8F)
            };
            status.Left = 43; status.Top = 287; status.Width = 315; status.Height = 25;
            status.Text = "업데이트 확인 중";
            status.ForeColor = Color.FromArgb(184, 168, 255);
            progress.Left = 43; progress.Top = 322; progress.Width = 315; progress.Height = 7;
            progress.Style = ProgressBarStyle.Marquee; progress.MarqueeAnimationSpeed = 24;
            Controls.AddRange(new Control[] { artwork, logo, title, subtitle, copyright, status, progress, close });
            close.BringToFront();
            Shown += async (_, __) => await StartAsync();
            FormClosing += (_, __) => { if (!startupCompleted) StopStartupProcessTree(); };
            FormClosed += (_, __) => { artworkTimer.Stop(); foreach (Image frame in artworkFrames) frame.Dispose(); };
        }

        private void LoadArtwork()
        {
            Assembly assembly = Assembly.GetExecutingAssembly();
            foreach (string name in new[] { "LAKIS.Splash1", "LAKIS.Splash2" })
                using (Stream stream = assembly.GetManifestResourceStream(name))
                    if (stream != null) artworkFrames.Add(new Bitmap(stream));
        }

        private void DragWindow(object sender, MouseEventArgs eventArgs)
        {
            if (eventArgs.Button != MouseButtons.Left) return;
            ReleaseCapture();
            SendMessage(Handle, WM_NCLBUTTONDOWN, HTCAPTION, 0);
        }

        private void CancelStartup()
        {
            userCancelled = true;
            if (!startupCompleted) StopStartupProcessTree();
            Close();
        }

        private void StopStartupProcessTree()
        {
            Process process = startupProcess;
            if (process == null || startupCompleted) return;
            try
            {
                process.Refresh();
                if (process.HasExited) return;
                string expected = Path.GetFullPath(Path.Combine(root, "python_embeded", "pythonw.exe"));
                if (!String.Equals(Path.GetFullPath(process.MainModule.FileName), expected,
                                   StringComparison.OrdinalIgnoreCase) ||
                    process.StartTime != startupProcessStartedAt)
                    throw new InvalidOperationException("Startup process identity changed; refusing termination.");
                string taskkill = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "taskkill.exe");
                using (Process killer = Process.Start(new ProcessStartInfo {
                    FileName = taskkill, Arguments = "/PID " + process.Id + " /T /F",
                    UseShellExecute = false, CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden,
                }))
                {
                    if (killer == null || !killer.WaitForExit(10000))
                        throw new IOException("Owned startup process cleanup did not complete.");
                }
                if (!process.WaitForExit(5000))
                    throw new IOException("Owned startup process remains alive.");
            }
            catch (Exception error)
            {
                // Never fall back to killing every Python or process under root.
                try { File.AppendAllText(Path.Combine(root, "launcher-cleanup.log"),
                    DateTime.UtcNow.ToString("O") + " " + error.Message + Environment.NewLine); }
                catch { }
            }
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            using (var border = new Pen(Color.FromArgb(47, 54, 73)))
                e.Graphics.DrawRectangle(border, 0, 0, ClientSize.Width - 1, ClientSize.Height - 1);
        }

        private static string ReadVersion(string installRoot)
        {
            try
            {
                string path = PrivateLukeBuild
                    ? Path.Combine(installRoot, "ComfyUI", "LAKIS_LUKE", "LUKE_VERSION")
                    : (DevelopmentBuild
                        ? Path.Combine(installRoot, "ComfyUI", "LAKIS_DEV", "DEV_VERSION")
                        : Path.Combine(installRoot, "VERSION"));
                return "v" + File.ReadAllText(path).Trim();
            }
            catch { return "LAKIS Studio"; }
        }

        private static bool IsProtectedUserPath(string relative)
        {
            string normalized = relative.Replace('\\', '/').TrimStart('/');
            foreach (string prefix in new[] {
                "ComfyUI/models/", "ComfyUI/user/", "ComfyUI/input/", "ComfyUI/output/"
            })
                if (normalized.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) return true;
            return false;
        }

        private static string ResolveManagedPath(string installRoot, string relative)
        {
            if (String.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative))
                throw new InvalidDataException("잘못된 관리 파일 경로입니다.");
            string normalized = relative.Replace('\\', '/');
            if (normalized.Split('/').Any(part => part == "..") || IsProtectedUserPath(normalized))
                throw new InvalidDataException("사용자 데이터 또는 설치 루트 밖 경로는 복구할 수 없습니다: " + relative);
            string rootFull = Path.GetFullPath(installRoot)
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                + Path.DirectorySeparatorChar;
            string full = Path.GetFullPath(Path.Combine(installRoot,
                normalized.Replace('/', Path.DirectorySeparatorChar)));
            if (!full.StartsWith(rootFull, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("설치 루트 밖 경로입니다: " + relative);
            return full;
        }

        private static string ReleaseAssetUrl(string version, string asset)
        {
            return "https://github.com/Jeong-Luke/LAKIS/releases/download/v" +
                version + "/" + asset;
        }

        private static bool UsesReleaseLayout(string installRoot)
        {
            string versionPath = Path.Combine(installRoot, "VERSION");
            Version version;
            return File.Exists(versionPath) &&
                Version.TryParse(File.ReadAllText(versionPath).Trim(), out version) &&
                version >= new Version(7, 5, 0);
        }

        private static bool TryGetReleaseLayout(string installRoot,
            out ReleaseLayout layout, out string layoutJson, out string failure)
        {
            layout = null; layoutJson = null; failure = null;
            try
            {
                string versionPath = Path.Combine(installRoot, "VERSION");
                string version = File.Exists(versionPath) ? File.ReadAllText(versionPath).Trim() : "";
                Version parsed;
                if (!Version.TryParse(version, out parsed))
                    throw new InvalidDataException("VERSION을 확인할 수 없습니다.");

                var request = (HttpWebRequest)WebRequest.Create(
                    ReleaseAssetUrl(version, "release-layout.json") +
                    "?t=" + DateTimeOffset.UtcNow.ToUnixTimeSeconds());
                request.UserAgent = "LAKIS-Consistency/" + version;
                request.Timeout = 10000;
                request.ReadWriteTimeout = 10000;
                request.CachePolicy = new System.Net.Cache.RequestCachePolicy(
                    System.Net.Cache.RequestCacheLevel.NoCacheNoStore);
                using (var response = request.GetResponse())
                using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8, true))
                    layoutJson = reader.ReadToEnd();

                var serializer = new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024 };
                layout = serializer.Deserialize<ReleaseLayout>(layoutJson);
                if (layout == null || layout.schema != 1 ||
                    !String.Equals(layout.product, "LAKIS", StringComparison.Ordinal) ||
                    !String.Equals(layout.version, version, StringComparison.Ordinal) ||
                    layout.files == null || layout.files.Count < 10)
                    throw new InvalidDataException("release-layout.json 내용이 올바르지 않습니다.");

                var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (ReleaseLayoutFile entry in layout.files)
                {
                    if (entry == null || entry.size < 0 || !seen.Add(entry.path ?? ""))
                        throw new InvalidDataException("release-layout.json 파일 목록이 올바르지 않습니다.");
                    ResolveManagedPath(installRoot, entry.path);
                }
                foreach (string retired in layout.retired ?? new List<string>())
                    ResolveManagedPath(installRoot, retired);
                return true;
            }
            catch (Exception error)
            {
                failure = error.Message;
                layout = null; layoutJson = null;
                return false;
            }
        }

        private static List<string> FindLayoutProblems(string installRoot, ReleaseLayout layout)
        {
            var failures = new List<string>();
            foreach (ReleaseLayoutFile entry in layout.files)
            {
                string path = ResolveManagedPath(installRoot, entry.path);
                if (!File.Exists(path)) failures.Add("누락: " + entry.path);
                else if (new FileInfo(path).Length != entry.size)
                    failures.Add("크기 불일치: " + entry.path);
                if (failures.Count >= 8) return failures;
            }
            foreach (string retired in layout.retired ?? new List<string>())
            {
                string path = ResolveManagedPath(installRoot, retired);
                if (File.Exists(path) || Directory.Exists(path))
                    failures.Add("구버전 잔재: " + retired);
                if (failures.Count >= 8) break;
            }
            return failures;
        }

        private static void DownloadFile(string url, string destination, string userAgent)
        {
            string temporary = destination + ".part";
            if (File.Exists(temporary)) File.Delete(temporary);
            var request = (HttpWebRequest)WebRequest.Create(
                url + "?t=" + DateTimeOffset.UtcNow.ToUnixTimeSeconds());
            request.UserAgent = userAgent;
            request.Timeout = 30000;
            request.ReadWriteTimeout = 30000;
            request.CachePolicy = new System.Net.Cache.RequestCachePolicy(
                System.Net.Cache.RequestCacheLevel.NoCacheNoStore);
            using (var response = request.GetResponse())
            using (var input = response.GetResponseStream())
            using (var output = new FileStream(temporary, FileMode.Create, FileAccess.Write, FileShare.None))
                input.CopyTo(output);
            if (File.Exists(destination)) File.Delete(destination);
            File.Move(temporary, destination);
        }

        private static void ExtractRepairPack(string archivePath, string payloadRoot)
        {
            if (Directory.Exists(payloadRoot)) Directory.Delete(payloadRoot, true);
            Directory.CreateDirectory(payloadRoot);
            string rootFull = Path.GetFullPath(payloadRoot)
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                + Path.DirectorySeparatorChar;
            using (ZipArchive archive = ZipFile.OpenRead(archivePath))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    string relative = entry.FullName.Replace('\\', '/');
                    if (String.IsNullOrWhiteSpace(relative)) continue;
                    string target = Path.GetFullPath(Path.Combine(payloadRoot,
                        relative.Replace('/', Path.DirectorySeparatorChar)));
                    if (!target.StartsWith(rootFull, StringComparison.OrdinalIgnoreCase))
                        throw new InvalidDataException("RepairPack 경로가 올바르지 않습니다.");
                    if (String.IsNullOrEmpty(entry.Name))
                    {
                        Directory.CreateDirectory(target);
                        continue;
                    }
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    entry.ExtractToFile(target, true);
                }
            }
        }

        private static string QuoteNativeArgument(string value)
        {
            return "\"" + value.Replace("\"", "\\\"") + "\"";
        }

        private static bool ScheduleAutomaticRepair(string installRoot,
            ReleaseLayout layout, string layoutJson, out string failure)
        {
            failure = null;
            string staging = Path.Combine(Path.GetTempPath(),
                "LAKIS-AutoRepair-" + Guid.NewGuid().ToString("N"));
            try
            {
                Directory.CreateDirectory(staging);
                string zip = Path.Combine(staging, "LAKIS_RepairPack.zip");
                string payload = Path.Combine(staging, "payload");
                DownloadFile(ReleaseAssetUrl(layout.version, "LAKIS_RepairPack.zip"),
                    zip, "LAKIS-AutoRepair/" + layout.version);
                ExtractRepairPack(zip, payload);

                List<string> stagedProblems = FindLayoutProblems(payload, layout);
                if (stagedProblems.Count > 0)
                    throw new InvalidDataException("복구 패키지 검증 실패:\n" +
                        String.Join("\n", stagedProblems.ToArray()));

                string layoutPath = Path.Combine(staging, "release-layout.json");
                File.WriteAllText(layoutPath, layoutJson, new UTF8Encoding(false));
                string helper = Path.Combine(staging, "apply-repair.ps1");
                string script = String.Join("\r\n", new[] {
                    "param([string]$InstallRoot,[string]$PayloadRoot,[string]$LayoutPath,[int]$ParentPid,[string]$StagingRoot)",
                    "$ErrorActionPreference='Stop'",
                    "Add-Type -AssemblyName System.Windows.Forms",
                    "$failed=$false",
                    "try {",
                    "try { Wait-Process -Id $ParentPid -ErrorAction SilentlyContinue } catch {}",
                    "Start-Sleep -Milliseconds 700",
                    "$layout=Get-Content -Raw -Encoding UTF8 -LiteralPath $LayoutPath | ConvertFrom-Json",
                    "$root=[IO.Path]::GetFullPath($InstallRoot).TrimEnd('\\')+'\\'",
                    "foreach($entry in $layout.files){",
                    "  $rel=([string]$entry.path).Replace('/','\\')",
                    "  $src=[IO.Path]::GetFullPath((Join-Path $PayloadRoot $rel))",
                    "  $dst=[IO.Path]::GetFullPath((Join-Path $InstallRoot $rel))",
                    "  if(-not $dst.StartsWith($root,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe repair path'}",
                    "  if((-not [IO.File]::Exists($dst)) -or ([IO.FileInfo]$dst).Length -ne [int64]$entry.size){",
                    "    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($dst)) | Out-Null",
                    "    Copy-Item -LiteralPath $src -Destination $dst -Force",
                    "  }",
                    "}",
                    "foreach($retired in @($layout.retired)){",
                    "  $dst=[IO.Path]::GetFullPath((Join-Path $InstallRoot (([string]$retired).Replace('/','\\'))))",
                    "  if(-not $dst.StartsWith($root,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe retired path'}",
                    "  if(Test-Path -LiteralPath $dst -PathType Leaf){Remove-Item -LiteralPath $dst -Force}",
                    "  elseif(Test-Path -LiteralPath $dst -PathType Container){Remove-Item -LiteralPath $dst -Recurse -Force}",
                    "}",
                    "foreach($entry in $layout.files){",
                    "  $dst=[IO.Path]::GetFullPath((Join-Path $InstallRoot (([string]$entry.path).Replace('/','\\'))))",
                    "  if((-not [IO.File]::Exists($dst)) -or ([IO.FileInfo]$dst).Length -ne [int64]$entry.size){throw ('Repair post-check failed: '+$entry.path)}",
                    "}",
                    "foreach($retired in @($layout.retired)){",
                    "  $dst=[IO.Path]::GetFullPath((Join-Path $InstallRoot (([string]$retired).Replace('/','\\'))))",
                    "  if(Test-Path -LiteralPath $dst){throw ('Repair retired-path post-check failed: '+$retired)}",
                    "}",
                    "Start-Process -FilePath (Join-Path $InstallRoot 'LAKIS.exe') -WorkingDirectory $InstallRoot",
                    "} catch {",
                    "  $failed=$true",
                    "  [Windows.Forms.MessageBox]::Show('자동 복구에 실패했습니다.`nLAKIS Setup을 다시 실행하여 Repair를 진행해 주세요.','LAKIS 자동 복구 실패','OK','Error') | Out-Null",
                    "}",
                    "Start-Sleep -Seconds 1",
                    "Remove-Item -LiteralPath $StagingRoot -Recurse -Force -ErrorAction SilentlyContinue",
                    "if($failed){exit 1}"
                });
                File.WriteAllText(helper, script, new UTF8Encoding(false));

                string stateRoot = Path.Combine(installRoot, ".lakis");
                Directory.CreateDirectory(stateRoot);
                File.WriteAllText(Path.Combine(stateRoot, "release-layout-repair.attempt"),
                    layout.version, new UTF8Encoding(false));

                var info = new ProcessStartInfo {
                    FileName = "powershell.exe",
                    Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " +
                        QuoteNativeArgument(helper) + " -InstallRoot " + QuoteNativeArgument(installRoot) +
                        " -PayloadRoot " + QuoteNativeArgument(payload) +
                        " -LayoutPath " + QuoteNativeArgument(layoutPath) +
                        " -ParentPid " + Process.GetCurrentProcess().Id +
                        " -StagingRoot " + QuoteNativeArgument(staging),
                    WorkingDirectory = installRoot,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                Process.Start(info);
                return true;
            }
            catch (Exception error)
            {
                failure = error.Message;
                try { if (Directory.Exists(staging)) Directory.Delete(staging, true); } catch { }
                return false;
            }
        }

        private void SetStatus(string text)
        {
            if (!IsDisposed) status.Text = text;
        }

        private async Task StartAsync()
        {
            string python = Path.Combine(root, "python_embeded", "pythonw.exe");
            string runtimeFolder = PrivateLukeBuild ? "LAKIS_LUKE" : (DevelopmentBuild ? "LAKIS_DEV" : "LAKIS");
            string launcher = Path.Combine(root, "ComfyUI", runtimeFolder, "external_ui", "launch_lakis.py");
            try
            {
                if (!DevelopmentBuild && !PrivateLukeBuild && UsesReleaseLayout(root))
                {
                    SetStatus("GitHub와 설치 파일 동일성 검사 중");
                    ReleaseLayout layout = null;
                    string layoutJson = null;
                    string layoutFailure = null;
                    bool layoutLoaded = await Task.Run(() =>
                        TryGetReleaseLayout(root, out layout, out layoutJson, out layoutFailure));
                    if (!layoutLoaded)
                    {
                        MessageBox.Show(this,
                            "GitHub와 설치 파일의 동일성 검사를 완료하지 못했습니다.\n" +
                            "네트워크 연결을 확인해 주세요.\n" +
                            "동일성 검사 없이 LAKIS를 실행합니다.",
                            "LAKIS 동일성 검사", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    }
                    else
                    {
                        List<string> layoutProblems = FindLayoutProblems(root, layout);
                        string attemptMarker = Path.Combine(root, ".lakis", "release-layout-repair.attempt");
                        if (layoutProblems.Count == 0)
                        {
                            try { if (File.Exists(attemptMarker)) File.Delete(attemptMarker); } catch { }
                            SetStatus("설치 파일 동일성 확인 완료");
                        }
                        else if (File.Exists(attemptMarker))
                        {
                            progress.MarqueeAnimationSpeed = 0;
                            MessageBox.Show(this,
                                "자동 복구에 실패했습니다.\n" +
                                "LAKIS Setup을 다시 실행하여 Repair를 진행해 주세요.",
                                "LAKIS 자동 복구 실패", MessageBoxButtons.OK, MessageBoxIcon.Error);
                            Close(); return;
                        }
                        else
                        {
                            MessageBox.Show(this,
                                "설치 파일이 현재 버전과 일치하지 않습니다.\n자동 복구를 시작합니다.",
                                "LAKIS 자동 복구", MessageBoxButtons.OK, MessageBoxIcon.Information);
                            SetStatus("자동 복구 준비 중");
                            string repairFailure = null;
                            bool repairScheduled = await Task.Run(() =>
                                ScheduleAutomaticRepair(root, layout, layoutJson, out repairFailure));
                            if (!repairScheduled)
                            {
                                progress.MarqueeAnimationSpeed = 0;
                                MessageBox.Show(this,
                                    "자동 복구에 실패했습니다.\n" +
                                    "LAKIS Setup을 다시 실행하여 Repair를 진행해 주세요.",
                                    "LAKIS 자동 복구 실패", MessageBoxButtons.OK, MessageBoxIcon.Error);
                            }
                            Close(); return;
                        }
                    }
                }

                SetStatus(PrivateLukeBuild ? "개인판 시작 중 · 자동 업데이트 꺼짐" : (DevelopmentBuild ? "개발판 시작 중 · 자동 업데이트 꺼짐" : "업데이트 확인 중"));
                string patcher = Path.Combine(root, "LAKIS_Patcher.exe");
                string updater = File.Exists(patcher) ? patcher : Path.Combine(root, "LAKIS_Updater.exe");
                string currentText = File.Exists(Path.Combine(root, "VERSION"))
                    ? File.ReadAllText(Path.Combine(root, "VERSION")).Trim() : "0.0.0";
                Version current;
                if (!Version.TryParse(currentText, out current)) current = new Version(0, 0, 0);
                var check = (DevelopmentBuild || PrivateLukeBuild) ? Tuple.Create(true, current, "") : await Task.Run(() => {
                    Version latest; string failure;
                    bool ok = TryGetLatestVersion(out latest, out failure);
                    return Tuple.Create(ok, latest, failure);
                });
                if (!check.Item1)
                    MessageBox.Show(this, "업데이트 확인에 실패했습니다. LAKIS는 계속 실행됩니다.\n\n" + check.Item3,
                        "LAKIS 업데이트", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                if (File.Exists(updater) && check.Item1 && check.Item2 > current &&
                    ShowUpdatePrompt(this, check.Item2, GetLatestReleaseNotes(check.Item2)))
                {
                    SetStatus("업데이트 프로그램 여는 중");
                    Process.Start(new ProcessStartInfo {
                        FileName = updater,
                        Arguments = "\"" + root.TrimEnd(Path.DirectorySeparatorChar) + "\" --launch-after-update",
                        WorkingDirectory = root, UseShellExecute = true,
                    });
                    Close(); return;
                }

                // Recovery check must be reachable even when runtime files are missing.
                if (!File.Exists(python) || !File.Exists(launcher))
                {
                    MessageBox.Show(this, "LAKIS 실행 파일을 찾을 수 없습니다. 설치를 다시 진행해 주세요.",
                        "LAKIS 실행 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    Close(); return;
                }

                SetStatus("ComfyUI 백엔드 시작 중");
                var startInfo = new ProcessStartInfo {
                    FileName = python, Arguments = "-s \"" + launcher + "\"",
                    WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
                };
                if (DevelopmentBuild)
                {
                    startInfo.EnvironmentVariables["LAKIS_COMFY_PORT"] = FindAvailableLoopbackPort(8190).ToString();
                    startInfo.EnvironmentVariables["LAKIS_DEVELOPMENT"] = "1";
                    startInfo.EnvironmentVariables["LAKIS_DESKTOP_HOST"] =
                        Path.Combine(root, "LAKIS_DEV_Desktop.exe");
                }
                else if (PrivateLukeBuild)
                {
                    startInfo.EnvironmentVariables["LAKIS_LUKE"] = "1";
                    startInfo.EnvironmentVariables["LAKIS_DESKTOP_HOST"] =
                        Path.Combine(root, "LUKIS_Desktop.exe");
                }
                else
                {
                    // Public LAKIS must not inherit DEKIS/LUKIS identity or experiment
                    // flags from the parent environment. Fail closed to the public runtime.
                    startInfo.EnvironmentVariables["LAKIS_DEVELOPMENT"] = "0";
                    startInfo.EnvironmentVariables["LAKIS_LUKE"] = "0";
                    startInfo.EnvironmentVariables["LAKIS_FULL_TURBO_EXPERIMENT"] = "0";
                    startInfo.EnvironmentVariables["LAKIS_HALF_RES_FAST_EXPERIMENT"] = "0";
                    startInfo.EnvironmentVariables["LAKIS_LOCAL_INPAINT_V2"] = "1";
                    startInfo.EnvironmentVariables["LAKIS_COMFY_PORT"] = "8189";
                    startInfo.EnvironmentVariables["LAKIS_DESKTOP_HOST"] =
                        Path.Combine(root, "LAKIS_Desktop.exe");
                }
                startInfo.EnvironmentVariables["LORA_MANAGER_SETTINGS_DIR"] =
                    Path.Combine(root, "ComfyUI", "user", "default", "lora-manager");
                Process process = Process.Start(startInfo);
                startupProcess = process;
                startupProcessStartedAt = process.StartTime;
                string launcherState = Path.Combine(root, "ComfyUI", runtimeFolder,
                    PrivateLukeBuild ? "lakis_luke_launcher_state.json" :
                    (DevelopmentBuild ? "lakis_dev_launcher_state.json" : "lakis_launcher_state.json"));
                bool ready = await Task.Run(() => WaitForLauncherReady(process, launcherState, 180));
                if (userCancelled || IsDisposed) return;
                if (!ready)
                {
                    string failureMessage = GetLauncherFailureMessage(launcherState, process);
                    MessageBox.Show(this, failureMessage,
                        "LAKIS 실행 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    Close();
                    return;
                }
                SetStatus((PrivateLukeBuild ? "LUKIS" : "LAKIS") + " Studio 화면 준비 중");
                bool desktopReady = await Task.Run(() => WaitForDesktopWindow(process, launcherState, 45));
                if (userCancelled || IsDisposed) return;
                if (!desktopReady)
                {
                    progress.MarqueeAnimationSpeed = 0;
                    SetStatus((PrivateLukeBuild ? "LUKIS" : "LAKIS") + " Studio 화면을 열지 못했습니다");
                    MessageBox.Show(this, "LAKIS 백엔드는 준비되었지만 화면이 열리지 않았습니다. 이 창을 닫지 않고 유지합니다.",
                        "LAKIS 실행 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }
                startupCompleted = true;
                SetStatus((PrivateLukeBuild ? "LUKIS" : "LAKIS") + " Studio 실행 완료");
                await Task.Delay(750);
                Close();
            }
            catch (Exception error)
            {
                MessageBox.Show(this, "LAKIS를 실행하지 못했습니다.\n\n" + error.Message,
                    "LAKIS 실행 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
                Close();
            }
        }

        [DllImport("user32.dll")]
        private static extern bool ReleaseCapture();

        [DllImport("user32.dll")]
        private static extern IntPtr SendMessage(IntPtr window, int message, int wParam, int lParam);

        private const int WM_NCLBUTTONDOWN = 0x00A1;
        private const int HTCAPTION = 2;
    }

    private static bool TryReadLauncherState(
        string statePath, int expectedLauncherPid,
        out Dictionary<string, object> state)
    {
        state = null;
        try
        {
            string json;
            using (var stream = new FileStream(statePath, FileMode.Open, FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete))
            using (var reader = new StreamReader(stream, Encoding.UTF8, true))
                json = reader.ReadToEnd();
            var parsed = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(json);
            object pidValue;
            int launcherPid;
            if (parsed == null || !parsed.TryGetValue("launcher_pid", out pidValue) ||
                !Int32.TryParse(Convert.ToString(pidValue), out launcherPid) ||
                launcherPid != expectedLauncherPid)
                return false;
            state = parsed;
            return true;
        }
        catch { return false; }
    }

    private static bool WaitForLauncherReady(Process process, string statePath, int timeoutSeconds)
    {
        DateTime deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        while (DateTime.UtcNow < deadline)
        {
            if (process == null || process.HasExited) return false;
            Dictionary<string, object> state;
            if (TryReadLauncherState(statePath, process.Id, out state))
            {
                object value;
                string classification = state.TryGetValue("classification", out value)
                    ? Convert.ToString(value) : "";
                if (classification == "LAKIS_READY") return true;
                if (classification.StartsWith("LAKIS_") && classification.EndsWith("_FAILED"))
                    return false;
            }
            Thread.Sleep(350);
        }
        return false;
    }

    private static int FindAvailableLoopbackPort(int preferredPort)
    {
        try
        {
            var probe = new TcpListener(System.Net.IPAddress.Loopback, preferredPort);
            probe.Start();
            probe.Stop();
            return preferredPort;
        }
        catch (SocketException)
        {
            var probe = new TcpListener(System.Net.IPAddress.Loopback, 0);
            probe.Start();
            int port = ((System.Net.IPEndPoint)probe.LocalEndpoint).Port;
            probe.Stop();
            return port;
        }
    }

    private static string GetLauncherFailureMessage(string statePath, Process process)
    {
        Dictionary<string, object> state;
        if (process != null && TryReadLauncherState(statePath, process.Id, out state))
        {
            object codeValue;
            object classValue;
            string code = state.TryGetValue("error_code", out codeValue) ? Convert.ToString(codeValue) : "";
            string classification = state.TryGetValue("classification", out classValue) ? Convert.ToString(classValue) : "";
            if (!String.IsNullOrEmpty(code) || !String.IsNullOrEmpty(classification))
                return "LAKIS 시작에 실패했습니다.\n\n오류 코드: " + code + "\n상태: " + classification +
                    "\n\n자세한 내용은 런처 로그를 확인해 주세요.";
        }
        return "LAKIS가 제한 시간 안에 준비되지 않았습니다. 런처 로그를 확인해 주세요.";
    }

    private static bool WaitForDesktopWindow(
        Process startupProcess, string statePath, int timeoutSeconds)
    {
        DateTime deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        while (DateTime.UtcNow < deadline)
        {
            try
            {
                Dictionary<string, object> state;
                object pidValue;
                int desktopPid;
                if (startupProcess != null &&
                    TryReadLauncherState(statePath, startupProcess.Id, out state) &&
                    state.TryGetValue("desktop_pid", out pidValue) &&
                    Int32.TryParse(Convert.ToString(pidValue), out desktopPid) && desktopPid > 0)
                {
                    using (Process desktop = Process.GetProcessById(desktopPid))
                    {
                        desktop.Refresh();
                        if (!desktop.HasExited && desktop.MainWindowHandle != IntPtr.Zero)
                            return true;
                    }
                }
                if (startupProcess == null || startupProcess.HasExited) return false;
            }
            catch { }
            Thread.Sleep(250);
        }
        return false;
    }

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
                request.UserAgent = "LAKIS-Launcher/7.4.5";
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
            request.UserAgent = "LAKIS-Launcher/7.4.5";
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

    private static string GetLatestReleaseNotes(Version expected)
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create(LatestReleaseApiUrl + "?t=" + DateTimeOffset.UtcNow.ToUnixTimeSeconds());
            request.UserAgent = "LAKIS-Launcher/7.4.5";
            request.Accept = "application/vnd.github+json";
            request.Timeout = 12000; request.ReadWriteTimeout = 12000;
            request.AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate;
            string json;
            using (var response = request.GetResponse())
            using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8, true)) json = reader.ReadToEnd();
            var payload = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(json);
            string tag = payload.ContainsKey("tag_name") ? Convert.ToString(payload["tag_name"]).TrimStart('v', 'V') : "";
            Version published;
            if (!Version.TryParse(tag, out published) || published != expected) return "업데이트 세부 내용을 불러오지 못했습니다.";
            string body = payload.ContainsKey("body") ? Convert.ToString(payload["body"]).Trim() : "";
            if (String.IsNullOrWhiteSpace(body)) return "이번 버전의 릴리스 설명이 없습니다.";
            return body.Length > 1800 ? body.Substring(0, 1800) + "…" : body;
        }
        catch { return "업데이트 세부 내용을 불러오지 못했습니다."; }
    }

    private static bool ShowUpdatePrompt(IWin32Window owner, Version version, string releaseNotes)
    {
        using (var dialog = new Form())
        {
            dialog.Text = "LAKIS 업데이트";
            dialog.ClientSize = new Size(610, 430);
            dialog.StartPosition = FormStartPosition.CenterParent;
            dialog.FormBorderStyle = FormBorderStyle.FixedDialog;
            dialog.MaximizeBox = false; dialog.MinimizeBox = false;
            dialog.Font = new Font("Segoe UI", 10F);
            var heading = new Label { Left = 24, Top = 20, Width = 560, Height = 34,
                Text = "LAKIS v" + version + " 업데이트가 있습니다.", Font = new Font("Segoe UI", 15F, FontStyle.Bold) };
            var guide = new Label { Left = 25, Top = 58, Width = 560, Height = 23,
                Text = "GitHub 릴리스에서 제공한 변경 내용입니다." };
            var notes = new TextBox { Left = 24, Top = 88, Width = 562, Height = 270,
                Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical,
                Text = releaseNotes, BackColor = SystemColors.Window, ForeColor = SystemColors.WindowText };
            var update = new Button { Left = 376, Top = 377, Width = 100, Height = 34,
                Text = "업데이트", DialogResult = DialogResult.Yes };
            var continueButton = new Button { Left = 486, Top = 377, Width = 100, Height = 34,
                Text = "그냥 실행", DialogResult = DialogResult.No };
            dialog.Controls.AddRange(new Control[] { heading, guide, notes, update, continueButton });
            dialog.AcceptButton = update; dialog.CancelButton = continueButton;
            dialog.Shown += (_, __) => update.Focus();
            return dialog.ShowDialog(owner) == DialogResult.Yes;
        }
    }

    [STAThread]
    private static void Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        try
        {
            using (Mutex.OpenExisting(DesktopMutexName))
            {
                MessageBox.Show("LAKIS가 이미 실행 중입니다.", ProductTitle,
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
        }
        catch (WaitHandleCannotBeOpenedException) { }
        bool ownsStartup;
        using (var mutex = new Mutex(true, StartupMutexName, out ownsStartup))
        {
            if (!ownsStartup)
            {
                MessageBox.Show("LAKIS가 이미 시작 중입니다.", ProductTitle,
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new StartupForm(root));
        }
    }
}
