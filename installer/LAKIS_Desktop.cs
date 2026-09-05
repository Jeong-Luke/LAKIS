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
    private readonly string targetUrl;
    private readonly string statePath;

    internal LakisDesktopForm(string url)
    {
        targetUrl = url;
        Text = "LAKIS Studio";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(1100, 720);
        Size = new Size(1600, 1000);
        AutoScaleMode = AutoScaleMode.Dpi;
        statePath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".lakis", "desktop-window.txt");
        RestoreWindowState();
        webView.Dock = DockStyle.Fill;
        Controls.Add(webView);
        Shown += async (_, __) => await InitializeAsync();
        FormClosing += (_, __) => SaveWindowState();
    }

    private async Task InitializeAsync()
    {
        try
        {
            string data = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".lakis", "webview2");
            Directory.CreateDirectory(data);
            CoreWebView2Environment environment = await CoreWebView2Environment.CreateAsync(null, data);
            await webView.EnsureCoreWebView2Async(environment);
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

    private void RestoreWindowState()
    {
        try
        {
            if (!File.Exists(statePath)) return;
            string[] values = File.ReadAllText(statePath).Split(',');
            if (values.Length != 4) return;
            int x, y, width, height;
            if (!Int32.TryParse(values[0], out x) || !Int32.TryParse(values[1], out y)
                || !Int32.TryParse(values[2], out width) || !Int32.TryParse(values[3], out height)) return;
            var bounds = new Rectangle(x, y, width, height);
            bool visible = false;
            foreach (Screen screen in Screen.AllScreens) if (screen.WorkingArea.IntersectsWith(bounds)) { visible = true; break; }
            if (!visible) return;
            StartPosition = FormStartPosition.Manual;
            Bounds = bounds;
        }
        catch { }
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
}
