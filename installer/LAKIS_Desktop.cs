using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal sealed class LakisDesktopForm : Form
{
    private readonly WebView2 webView = new WebView2();
    private readonly Panel titleBar = new Panel();
    private readonly Label titleLabel = new Label();
    private readonly PictureBox titleIcon = new PictureBox();
    private readonly Button minimizeButton = new Button();
    private readonly Button maximizeButton = new Button();
    private readonly Button closeButton = new Button();
    private readonly string targetUrl;
    private readonly string statePath;

    internal LakisDesktopForm(string url)
    {
        targetUrl = url;
        Text = "LAKIS Studio";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        FormBorderStyle = FormBorderStyle.None;
        BackColor = Color.FromArgb(10, 13, 20);
        StartPosition = FormStartPosition.Manual;
        ConfigureSafeWindowBounds();
        AutoScaleMode = AutoScaleMode.Dpi;
        ResizeRedraw = true;
        statePath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".lakis", "desktop-window.txt");
        RestoreWindowState();
        BuildTitleBar();
        webView.Dock = DockStyle.Fill;
        Controls.Add(webView);
        Controls.Add(titleBar);
        webView.Resize += (_, __) => ApplyResponsiveZoom();
        Shown += async (_, __) => await InitializeAsync();
        FormClosing += (_, __) => SaveWindowState();
    }

    private void BuildTitleBar()
    {
        titleBar.Dock = DockStyle.Top;
        titleBar.Height = 46;
        titleBar.BackColor = Color.FromArgb(10, 13, 20);
        titleBar.Padding = new Padding(14, 0, 0, 0);
        titleBar.MouseDown += TitleBarMouseDown;
        titleBar.DoubleClick += (_, __) => ToggleMaximize();

        titleIcon.Image = Icon.ToBitmap();
        titleIcon.SizeMode = PictureBoxSizeMode.Zoom;
        titleIcon.Size = new Size(22, 22);
        titleIcon.Location = new Point(14, 12);
        titleIcon.MouseDown += TitleBarMouseDown;

        titleLabel.Text = "LAKIS Studio";
        titleLabel.ForeColor = Color.FromArgb(210, 215, 228);
        titleLabel.Font = new Font("Segoe UI", 10F, FontStyle.Regular, GraphicsUnit.Point);
        titleLabel.AutoSize = true;
        titleLabel.Location = new Point(44, 13);
        titleLabel.MouseDown += TitleBarMouseDown;
        titleLabel.DoubleClick += (_, __) => ToggleMaximize();

        ConfigureCaptionButton(minimizeButton, "\uE921", (_, __) => WindowState = FormWindowState.Minimized);
        ConfigureCaptionButton(maximizeButton, "\uE922", (_, __) => ToggleMaximize());
        ConfigureCaptionButton(closeButton, "\uE8BB", (_, __) => Close());
        closeButton.FlatAppearance.MouseOverBackColor = Color.FromArgb(196, 43, 28);

        titleBar.Controls.Add(titleIcon);
        titleBar.Controls.Add(titleLabel);
        titleBar.Controls.Add(minimizeButton);
        titleBar.Controls.Add(maximizeButton);
        titleBar.Controls.Add(closeButton);
        titleBar.Resize += (_, __) => LayoutCaptionButtons();
        Resize += (_, __) => UpdateMaximizeGlyph();
        LayoutCaptionButtons();
    }

    private void ConfigureCaptionButton(Button button, string glyph, EventHandler click)
    {
        button.Text = glyph;
        button.Font = new Font("Segoe MDL2 Assets", 9F, FontStyle.Regular, GraphicsUnit.Point);
        button.ForeColor = Color.FromArgb(202, 208, 222);
        button.BackColor = Color.Transparent;
        button.FlatStyle = FlatStyle.Flat;
        button.FlatAppearance.BorderSize = 0;
        button.FlatAppearance.MouseOverBackColor = Color.FromArgb(37, 42, 54);
        button.FlatAppearance.MouseDownBackColor = Color.FromArgb(51, 57, 72);
        button.Size = new Size(48, 46);
        button.TabStop = false;
        button.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        button.Click += click;
    }

    private void LayoutCaptionButtons()
    {
        closeButton.Location = new Point(titleBar.ClientSize.Width - 48, 0);
        maximizeButton.Location = new Point(titleBar.ClientSize.Width - 96, 0);
        minimizeButton.Location = new Point(titleBar.ClientSize.Width - 144, 0);
    }

    private void ToggleMaximize()
    {
        WindowState = WindowState == FormWindowState.Maximized
            ? FormWindowState.Normal : FormWindowState.Maximized;
        UpdateMaximizeGlyph();
    }

    private void UpdateMaximizeGlyph()
    {
        maximizeButton.Text = WindowState == FormWindowState.Maximized ? "\uE923" : "\uE922";
    }

    private void TitleBarMouseDown(object sender, MouseEventArgs eventArgs)
    {
        if (eventArgs.Button != MouseButtons.Left) return;
        ReleaseCapture();
        SendMessage(Handle, WM_NCLBUTTONDOWN, HTCAPTION, 0);
    }

    protected override void WndProc(ref Message message)
    {
        if (message.Msg == WM_NCHITTEST && WindowState == FormWindowState.Normal)
        {
            base.WndProc(ref message);
            if ((int)message.Result == HTCLIENT)
            {
                Point cursor = PointToClient(Cursor.Position);
                int left = cursor.X <= ResizeBorderWidth ? 1 : 0;
                int right = cursor.X >= ClientSize.Width - ResizeBorderWidth ? 1 : 0;
                int top = cursor.Y <= ResizeBorderWidth ? 1 : 0;
                int bottom = cursor.Y >= ClientSize.Height - ResizeBorderWidth ? 1 : 0;
                if (top == 1 && left == 1) message.Result = (IntPtr)HTTOPLEFT;
                else if (top == 1 && right == 1) message.Result = (IntPtr)HTTOPRIGHT;
                else if (bottom == 1 && left == 1) message.Result = (IntPtr)HTBOTTOMLEFT;
                else if (bottom == 1 && right == 1) message.Result = (IntPtr)HTBOTTOMRIGHT;
                else if (left == 1) message.Result = (IntPtr)HTLEFT;
                else if (right == 1) message.Result = (IntPtr)HTRIGHT;
                else if (top == 1) message.Result = (IntPtr)HTTOP;
                else if (bottom == 1) message.Result = (IntPtr)HTBOTTOM;
            }
            return;
        }
        base.WndProc(ref message);
    }

    private async Task InitializeAsync()
    {
        try
        {
            string data = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".lakis", "webview2");
            Directory.CreateDirectory(data);
            CoreWebView2Environment environment = await CoreWebView2Environment.CreateAsync(null, data);
            await webView.EnsureCoreWebView2Async(environment);
            ApplyResponsiveZoom();
            webView.CoreWebView2.Settings.AreDevToolsEnabled = false;
            webView.CoreWebView2.Settings.IsStatusBarEnabled = false;
            webView.CoreWebView2.NewWindowRequested += (_, eventArgs) =>
            {
                eventArgs.Handled = true;
                Uri destination;
                if (!Uri.TryCreate(eventArgs.Uri, UriKind.Absolute, out destination)
                    || (destination.Scheme != Uri.UriSchemeHttp && destination.Scheme != Uri.UriSchemeHttps)) return;
                try { Process.Start(new ProcessStartInfo(destination.AbsoluteUri) { UseShellExecute = true }); }
                catch { }
            };
            webView.Source = new Uri(targetUrl);
        }
        catch (Exception error)
        {
            MessageBox.Show(
                "LAKIS 데스크톱 창을 시작하지 못했습니다.\nWebView2 Runtime을 설치하거나 LAKIS 복구를 실행해 주세요.\n\n" + error.Message,
                "LAKIS 실행 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Close();
        }
    }

    private bool RestoreWindowState()
    {
        try
        {
            if (!File.Exists(statePath)) return false;
            string[] values = File.ReadAllText(statePath).Split(',');
            if (values.Length != 4) return false;
            int x, y, width, height;
            if (!Int32.TryParse(values[0], out x) || !Int32.TryParse(values[1], out y)
                || !Int32.TryParse(values[2], out width) || !Int32.TryParse(values[3], out height)) return false;
            var bounds = new Rectangle(x, y, width, height);
            Screen target = null;
            foreach (Screen screen in Screen.AllScreens)
                if (screen.WorkingArea.IntersectsWith(bounds)) { target = screen; break; }
            if (target == null) return false;
            Rectangle work = target.WorkingArea;
            // Old releases could persist a narrow two-column window. Do not
            // restore it on a large display because it breaks the four-panel
            // LAKIS composition on the next startup.
            int safeRestoreWidth = Math.Max(MinimumSize.Width, (int)Math.Round(work.Width * 0.75));
            int safeRestoreHeight = Math.Max(MinimumSize.Height, (int)Math.Round(work.Height * 0.72));
            if (width < safeRestoreWidth || height < safeRestoreHeight) return false;
            width = Math.Min(Math.Max(width, MinimumSize.Width), work.Width);
            height = Math.Min(Math.Max(height, MinimumSize.Height), work.Height);
            x = Math.Max(work.Left, Math.Min(x, work.Right - width));
            y = Math.Max(work.Top, Math.Min(y, work.Bottom - height));
            StartPosition = FormStartPosition.Manual;
            Bounds = new Rectangle(x, y, width, height);
            return true;
        }
        catch { return false; }
    }

    private void ApplyResponsiveZoom()
    {
        if (webView.CoreWebView2 == null || webView.ClientSize.Width <= 0) return;
        // Keep enough CSS viewport width for the 1:1:2.5:1.5 four-panel
        // layout while still allowing a practical windowed minimum size.
        double zoom = Math.Min(1.0, Math.Max(0.68, webView.ClientSize.Width / 2100.0));
        if (Math.Abs(webView.ZoomFactor - zoom) > 0.01) webView.ZoomFactor = zoom;
    }

    private void ConfigureSafeWindowBounds()
    {
        Rectangle work = Screen.PrimaryScreen.WorkingArea;
        int minimumWidth = Math.Min(1500, work.Width);
        int minimumHeight = Math.Min(844, work.Height);
        MinimumSize = new Size(minimumWidth, minimumHeight);

        int width = Math.Max(minimumWidth, (int)(work.Width * 0.92));
        int height = (int)Math.Round(width * 9.0 / 16.0);
        int maximumHeight = (int)(work.Height * 0.92);
        if (height > maximumHeight)
        {
            height = Math.Max(minimumHeight, maximumHeight);
            width = (int)Math.Round(height * 16.0 / 9.0);
        }
        width = Math.Min(width, work.Width);
        height = Math.Min(height, work.Height);
        Bounds = new Rectangle(
            work.Left + (work.Width - width) / 2,
            work.Top + (work.Height - height) / 2,
            width, height);
    }

    private void SaveWindowState()
    {
        try
        {
            Rectangle bounds = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
            Directory.CreateDirectory(Path.GetDirectoryName(statePath));
            File.WriteAllText(statePath, String.Format("{0},{1},{2},{3}", bounds.X, bounds.Y, bounds.Width, bounds.Height));
        }
        catch { }
    }

    [STAThread]
    private static void Main(string[] args)
    {
        // A desktop shortcut launches this host without arguments. Route that
        // entry through LAKIS.exe so update checks and backend startup always
        // happen. launch_lakis.py supplies the URL when it is time to create
        // the actual WebView window, which avoids a launcher/host loop.
        if (args.Length == 0)
        {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string launcher = Path.Combine(root, "LAKIS.exe");
            if (!File.Exists(launcher))
            {
                MessageBox.Show("LAKIS 실행 파일을 찾을 수 없습니다. 복구 설치를 진행해 주세요.",
                    "LAKIS 실행 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }
            try
            {
                Process.Start(new ProcessStartInfo {
                    FileName = launcher,
                    WorkingDirectory = root,
                    UseShellExecute = true,
                });
            }
            catch (Exception error)
            {
                MessageBox.Show("LAKIS를 실행하지 못했습니다.\n\n" + error.Message,
                    "LAKIS 실행 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            return;
        }
        EnablePerMonitorDpi();
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        string url = args.Length > 0 ? args[0] : "http://127.0.0.1:8766/";
        Application.Run(new LakisDesktopForm(url));
    }

    private static void EnablePerMonitorDpi()
    {
        try { SetProcessDpiAwarenessContext(new IntPtr(-4)); }
        catch { try { SetProcessDPIAware(); } catch { } }
    }

    [DllImport("user32.dll")]
    private static extern bool SetProcessDpiAwarenessContext(IntPtr dpiContext);

    [DllImport("user32.dll")]
    private static extern bool SetProcessDPIAware();

    [DllImport("user32.dll")]
    private static extern bool ReleaseCapture();

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(IntPtr window, int message, int wParam, int lParam);

    private const int ResizeBorderWidth = 10;
    private const int WM_NCHITTEST = 0x0084;
    private const int WM_NCLBUTTONDOWN = 0x00A1;
    private const int HTCLIENT = 1;
    private const int HTCAPTION = 2;
    private const int HTLEFT = 10;
    private const int HTRIGHT = 11;
    private const int HTTOP = 12;
    private const int HTTOPLEFT = 13;
    private const int HTTOPRIGHT = 14;
    private const int HTBOTTOM = 15;
    private const int HTBOTTOMLEFT = 16;
    private const int HTBOTTOMRIGHT = 17;
}
