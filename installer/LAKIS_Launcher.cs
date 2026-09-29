using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
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
                Text = PrivateLukeBuild ? "L U K I S" : "L A K I S", Font = new Font("Segoe UI", 20F, FontStyle.Bold),
                ForeColor = Color.FromArgb(225, 229, 255)
            };
            title.MouseDown += DragWindow;
            var subtitle = new Label {
                Left = 114, Top = 78, Width = 260, Height = 25,
                Text = PrivateLukeBuild ? "Studio" : (DevelopmentBuild ? "Studio · DEVELOPMENT" : "Studio"), Font = new Font("Segoe UI", 11F, FontStyle.Bold),
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
                Text = "© 2026 Luke Jeong. All rights reserved. · " + (PrivateLukeBuild ? "LUKIS " : "LAKIS ") + ReadVersion(installRoot),
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
            dialog.ClientSize = new Size(650, 560);
            dialog.StartPosition = FormStartPosition.CenterParent;
            dialog.FormBorderStyle = FormBorderStyle.FixedDialog;
            dialog.MaximizeBox = false; dialog.MinimizeBox = false;
            dialog.Font = new Font("Segoe UI", 10F);
            dialog.BackColor = Color.FromArgb(18, 21, 32);
            dialog.ForeColor = Color.FromArgb(238, 240, 248);
            dialog.Padding = new Padding(26, 22, 26, 20);
            var heading = new Label { Left = 26, Top = 22, Width = 598, Height = 36,
                Text = "LAKIS v" + version + " 업데이트", Font = new Font("Segoe UI", 16F, FontStyle.Bold),
                ForeColor = Color.FromArgb(244, 245, 252) };
            var guide = new Label { Left = 27, Top = 64, Width = 596, Height = 24,
                Text = "업데이트 내용을 확인한 뒤 진행해 주세요.",
                ForeColor = Color.FromArgb(174, 181, 201) };
            var notes = new RichTextBox { Left = 26, Top = 100, Width = 598, Height = 380,
                ReadOnly = true, ScrollBars = RichTextBoxScrollBars.Vertical, BorderStyle = BorderStyle.FixedSingle,
                BackColor = Color.FromArgb(12, 15, 24), ForeColor = Color.FromArgb(220, 224, 238),
                DetectUrls = false, TabStop = false };
            PopulateReleaseNotes(notes, releaseNotes);
            var update = new Button { Left = 414, Top = 505, Width = 100, Height = 36,
                Text = "업데이트", DialogResult = DialogResult.Yes };
            var continueButton = new Button { Left = 524, Top = 505, Width = 100, Height = 36,
                Text = "나중에", DialogResult = DialogResult.No };
            dialog.Controls.AddRange(new Control[] { heading, guide, notes, update, continueButton });
            dialog.AcceptButton = update; dialog.CancelButton = continueButton;
            dialog.Shown += (_, __) => update.Focus();
            return dialog.ShowDialog(owner) == DialogResult.Yes;
        }
    }

    private static void PopulateReleaseNotes(RichTextBox notes, string releaseNotes)
    {
        string text = releaseNotes ?? "";
        text = Regex.Replace(text, @"\[([^\]]+)\]\([^\)]+\)", "$1");
        text = text.Replace("`", "").Replace("\r\n", "\n").Replace('\r', '\n');
        string[] lines = text.Split('\n');
        notes.Clear();
        foreach (string sourceLine in lines)
        {
            string line = Regex.Replace(sourceLine.Trim(), @"^#{1,6}\s*", "");
            if (Regex.IsMatch(line, @"^LAKIS\s+v?\d+(\.\d+)+\s*(업데이트)?$", RegexOptions.IgnoreCase)) continue;
            if (line.Length == 0)
            {
                if (notes.TextLength > 0 && !notes.Text.EndsWith("\n\n")) notes.AppendText("\n");
                continue;
            }

            bool section = line.StartsWith("🚨") || line.StartsWith("✨") || line.StartsWith("ℹ") ||
                line == "치명적 버그 수정" || line == "주요 변경 사항" || line == "안내";
            bool bullet = Regex.IsMatch(line, @"^[-*•]\s+");
            if (bullet) line = "• " + Regex.Replace(line, @"^[-*•]\s+", "");

            notes.SelectionStart = notes.TextLength;
            notes.SelectionLength = 0;
            notes.SelectionFont = new Font("Segoe UI", section ? 11F : 10F,
                section ? FontStyle.Bold : FontStyle.Regular);
            notes.SelectionColor = section ? Color.FromArgb(176, 145, 255) : Color.FromArgb(220, 224, 238);
            notes.SelectionIndent = bullet ? 22 : 12;
            notes.SelectionHangingIndent = bullet ? -10 : 0;
            notes.SelectionRightIndent = 12;
            notes.AppendText(line + "\n");
            if (section) notes.AppendText("\n");
        }
        notes.SelectionStart = 0;
        notes.SelectionLength = 0;
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
