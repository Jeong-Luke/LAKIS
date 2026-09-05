using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Net;
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
        private readonly CenterCropPictureBox artwork = new CenterCropPictureBox();
        private readonly List<Image> artworkFrames = new List<Image>();
        private readonly System.Windows.Forms.Timer artworkTimer = new System.Windows.Forms.Timer();
        private int artworkIndex;

        internal StartupForm(string installRoot)
        {
            root = installRoot;
            Text = "LAKIS Studio";
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
                Text = "Studio", Font = new Font("Segoe UI", 11F, FontStyle.Bold),
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
                Text = "ⓒ 2026. Luke_Jeong All rights reserved. · LAKIS " + ReadVersion(installRoot),
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
            try { if (startupProcess != null && !startupProcess.HasExited) startupProcess.Kill(); }
            catch { }
            Close();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            using (var border = new Pen(Color.FromArgb(47, 54, 73)))
                e.Graphics.DrawRectangle(border, 0, 0, ClientSize.Width - 1, ClientSize.Height - 1);
        }

        private static string ReadVersion(string installRoot)
        {
            try { return "v" + File.ReadAllText(Path.Combine(installRoot, "VERSION")).Trim(); }
            catch { return "LAKIS Studio"; }
        }

        private void SetStatus(string text)
        {
            if (!IsDisposed) status.Text = text;
        }

        private async Task StartAsync()
        {
            string python = Path.Combine(root, "python_embeded", "pythonw.exe");
            string launcher = Path.Combine(root, "ComfyUI", "LAKIS_DEV", "external_ui", "launch_lakis.py");
            if (!File.Exists(python) || !File.Exists(launcher))
            {
                MessageBox.Show(this, "LAKIS 실행 파일을 찾을 수 없습니다. 설치를 다시 진행해 주세요.",
                    "LAKIS 실행 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
                Close(); return;
            }
            try
            {
                SetStatus("업데이트 확인 중");
                string patcher = Path.Combine(root, "LAKIS_Patcher.exe");
                string updater = File.Exists(patcher) ? patcher : Path.Combine(root, "LAKIS_Updater.exe");
                string currentText = File.Exists(Path.Combine(root, "VERSION"))
                    ? File.ReadAllText(Path.Combine(root, "VERSION")).Trim() : "0.0.0";
                Version current;
                if (!Version.TryParse(currentText, out current)) current = new Version(0, 0, 0);
                var check = await Task.Run(() => {
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

                SetStatus("ComfyUI 백엔드 시작 중");
                var startInfo = new ProcessStartInfo {
                    FileName = python, Arguments = "-s \"" + launcher + "\"",
                    WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
                };
                startInfo.EnvironmentVariables["LORA_MANAGER_SETTINGS_DIR"] =
                    Path.Combine(root, "ComfyUI", "user", "default", "lora-manager");
                Process process = Process.Start(startInfo);
                startupProcess = process;
                bool ready = await Task.Run(() => WaitForUi(process, 180));
                if (userCancelled || IsDisposed) return;
                if (!ready)
                {
                    MessageBox.Show(this, "LAKIS가 제한 시간 안에 준비되지 않았습니다. 런처 로그를 확인해 주세요.",
                        "LAKIS 실행 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    Close();
                    return;
                }
                SetStatus("LAKIS Studio 화면 준비 중");
                bool desktopReady = await Task.Run(() => WaitForDesktopWindow(process, 45));
                if (userCancelled || IsDisposed) return;
                if (!desktopReady)
                {
                    progress.MarqueeAnimationSpeed = 0;
                    SetStatus("LAKIS Studio 화면을 열지 못했습니다");
                    MessageBox.Show(this, "LAKIS 백엔드는 준비되었지만 화면이 열리지 않았습니다. 이 창을 닫지 않고 유지합니다.",
                        "LAKIS 실행 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }
                SetStatus("LAKIS Studio 실행 완료");
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

    private static bool WaitForUi(Process process, int timeoutSeconds)
    {
        DateTime deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        while (DateTime.UtcNow < deadline)
        {
            if (UiResponds()) return true;
            if (process == null || process.HasExited) return false;
            Thread.Sleep(350);
        }
        return false;
    }

    private static bool WaitForDesktopWindow(Process startupProcess, int timeoutSeconds)
    {
        DateTime deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        while (DateTime.UtcNow < deadline)
        {
            try
            {
                foreach (Process desktop in Process.GetProcessesByName("LAKIS_Desktop"))
                {
                    try
                    {
                        desktop.Refresh();
                        if (!desktop.HasExited && desktop.MainWindowHandle != IntPtr.Zero)
                            return true;
                    }
                    finally { desktop.Dispose(); }
                }
                if (startupProcess == null || startupProcess.HasExited) return false;
            }
            catch { }
            Thread.Sleep(250);
        }
        return false;
    }

    private static bool UiResponds()
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:8766/");
            request.Timeout = 500; request.ReadWriteTimeout = 500;
            using (var response = (HttpWebResponse)request.GetResponse())
                return (int)response.StatusCode < 500;
        }
        catch { return false; }
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
                request.UserAgent = "LAKIS-Launcher/7.2.1";
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
            request.UserAgent = "LAKIS-Launcher/7.2.1";
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
            request.UserAgent = "LAKIS-Launcher/7.2.1";
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
            using (Mutex.OpenExisting("Local\\LAKIS-Studio-Desktop"))
            {
                MessageBox.Show("LAKIS가 이미 실행 중입니다.", "LAKIS Studio",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
        }
        catch (WaitHandleCannotBeOpenedException) { }
        bool ownsStartup;
        using (var mutex = new Mutex(true, "Local\\LAKIS-Studio-Startup", out ownsStartup))
        {
            if (!ownsStartup)
            {
                MessageBox.Show("LAKIS가 이미 시작 중입니다.", "LAKIS Studio",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new StartupForm(root));
        }
    }
}
