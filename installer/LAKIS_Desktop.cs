using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal sealed class LakisDesktopForm : Form
{
#if LAKIS_DEV
    private const string ProductTitle = "LAKIS Studio DEV";
    private const string LauncherFileName = "LAKIS_DEV.exe";
    private const string DesktopMutexName = "Local\\LAKIS-Studio-DEV-Desktop";
    private const string WindowStateFolder = ".lakis-dev";
#else
    private const string ProductTitle = "LAKIS Studio";
    private const string LauncherFileName = "LAKIS.exe";
    private const string DesktopMutexName = "Local\\LAKIS-Studio-Desktop";
    private const string WindowStateFolder = ".lakis";
#endif
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
        Text = ProductTitle;
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        FormBorderStyle = FormBorderStyle.None;
        BackColor = Color.FromArgb(10, 13, 20);
        StartPosition = FormStartPosition.Manual;
        ConfigureSafeWindowBounds();
        AutoScaleMode = AutoScaleMode.Dpi;
        ResizeRedraw = true;
        statePath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, WindowStateFolder, "desktop-window.txt");
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

        titleLabel.Text = ProductTitle;
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

#if LAKIS_DEV
    internal async Task<bool> TriggerDevelopmentErrorAsync(string payloadJson)
    {
        if (webView.CoreWebView2 == null) return false;
        string result = await webView.CoreWebView2.ExecuteScriptAsync(
            "window.LAKISDevTriggerError(" + payloadJson + ")");
        return String.Equals(result, "true", StringComparison.OrdinalIgnoreCase);
    }
#endif

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
            string launcher = Path.Combine(root, LauncherFileName);
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
        bool ownsDesktop;
        using (var mutex = new Mutex(true, DesktopMutexName, out ownsDesktop))
        {
            if (!ownsDesktop) return;
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            string url = args.Length > 0 ? args[0] : "http://127.0.0.1:8766/";
            var mainForm = new LakisDesktopForm(url);
#if LAKIS_DEV
            mainForm.Shown += (_, __) => {
                var errorTool = new LakisDevErrorToolForm(mainForm);
                errorTool.PositionNextTo(mainForm);
                errorTool.Show(mainForm);
            };
#endif
            Application.Run(mainForm);
        }
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

#if LAKIS_DEV
internal sealed class LakisDevErrorToolForm : Form
{
    private readonly LakisDesktopForm target;
    private readonly Label status = new Label();
    private readonly ComboBox catalog = new ComboBox();

    private sealed class Scenario
    {
        internal readonly string Label, Code, Stage, NodeId, NodeType, Message;
        internal Scenario(string label, string code, string stage, string nodeId, string nodeType, string message)
        { Label=label; Code=code; Stage=stage; NodeId=nodeId; NodeType=nodeType; Message=message; }
        public override string ToString() { return Code + " · " + Label; }
    }

    internal LakisDevErrorToolForm(LakisDesktopForm targetForm)
    {
        target = targetForm;
        Text = "LAKIS DEV 오류 시험기";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        ClientSize = new Size(310, 430);
        FormBorderStyle = FormBorderStyle.FixedToolWindow;
        MaximizeBox = false; MinimizeBox = false; ShowInTaskbar = false;
        BackColor = Color.FromArgb(19, 22, 31); ForeColor = Color.White;
        Font = new Font("Segoe UI", 9.5F);
        Controls.Add(new Label {
            Left = 18, Top = 16, Width = 275, Height = 44,
            Text = "오류창 표시 시험\n실제 생성과 백엔드는 중단하지 않습니다.",
            ForeColor = Color.FromArgb(255, 158, 174),
        });
        AddButton("일반 생성 오류", 68, "LKS-GEN-1001", "생성 준비", null, null,
            "테스트용 생성 오류입니다.");
        AddButton("Nova 가까움 오류", 112, "LKS-GEN-1301", "Initial", "1634:1622", "KSampler",
            "Nova Anima의 가까움 구도 조건을 가정한 테스트 오류입니다.");
        AddButton("GPU 메모리 오류", 156, "LKS-GEN-1004", "모델 로딩", "890:1365", "UNETLoader",
            "GPU 모델 메모리 상태가 불안정해 생성이 중단됐어요.");
        AddButton("업스케일 오류", 200, "LKS-GEN-1601", "Upscale", "1541:1538", "UltimateSDUpscale",
            "업스케일 단계에서 발생한 테스트 오류입니다.");
        Controls.Add(new Label { Left=18, Top=250, Width=274, Height=22,
            Text="전체 오류 코드 시험", ForeColor=Color.FromArgb(224, 228, 240) });
        catalog.SetBounds(18, 274, 274, 32);
        catalog.DropDownStyle = ComboBoxStyle.DropDownList;
        foreach (Scenario item in AllScenarios()) catalog.Items.Add(item);
        if (catalog.Items.Count > 0) catalog.SelectedIndex = 0;
        Controls.Add(catalog);
        var trigger = new Button { Left=18, Top=314, Width=274, Height=36,
            Text="선택한 오류 발생", FlatStyle=FlatStyle.Flat,
            BackColor=Color.FromArgb(88, 27, 47), ForeColor=Color.White, Cursor=Cursors.Hand };
        trigger.FlatAppearance.BorderColor=Color.FromArgb(215, 68, 108);
        trigger.Click += async (_, __) => await ShowScenarioAsync(catalog.SelectedItem as Scenario);
        Controls.Add(trigger);
        status.SetBounds(18, 362, 275, 48);
        status.ForeColor = Color.FromArgb(167, 178, 199);
        status.Text = "버튼을 누르면 데키스 본창에 오류가 표시됩니다.";
        Controls.Add(status);
    }

    private void AddButton(string text, int top, string code, string stage,
                           string nodeId, string nodeType, string message)
    {
        var button = new Button {
            Left = 18, Top = top, Width = 274, Height = 36, Text = text,
            FlatStyle = FlatStyle.Flat, BackColor = Color.FromArgb(50, 29, 42),
            ForeColor = Color.FromArgb(255, 184, 202), Cursor = Cursors.Hand,
        };
        button.FlatAppearance.BorderColor = Color.FromArgb(155, 55, 82);
        button.Click += async (_, __) => await ShowScenarioAsync(
            new Scenario(text, code, stage, nodeId, nodeType, message));
        Controls.Add(button);
    }

    private async Task ShowScenarioAsync(Scenario item)
    {
        if (item == null) return;
        bool shown = await target.TriggerDevelopmentErrorAsync(
            BuildPayload(item.Code, item.Stage, item.NodeId, item.NodeType, item.Message));
        status.Text = shown ? item.Code + " 오류창을 표시했습니다." : "데키스 UI가 아직 준비되지 않았습니다.";
    }

    private static Scenario[] AllScenarios()
    {
        return new[] {
            new Scenario("일반 생성 실패","LKS-GEN-1001","생성","", "", "분류되지 않은 생성 오류입니다."),
            new Scenario("ComfyUI 연결 끊김","LKS-GEN-1002","연결","", "", "ComfyUI 연결이 끊어졌어요."),
            new Scenario("생성 큐 사용 중","LKS-GEN-1003","요청 검증","", "", "다른 생성 작업이 실행 중이에요."),
            new Scenario("GPU 상태 불안정","LKS-GEN-1004","모델 로딩","890:1365","UNETLoader","GPU 모델 메모리 상태가 불안정해요."),
            new Scenario("GPU 메모리 부족","LKS-GEN-1005","Initial","1634:1622","KSampler","GPU 메모리가 부족해요."),
            new Scenario("계산값 NaN/무한대","LKS-GEN-1006","Initial","1634:1622","KSampler","계산값이 불안정해요."),
            new Scenario("단계 시간 초과","LKS-GEN-1007","HighRez","1633:1612","KSampler","생성 단계가 제한 시간 안에 응답하지 않았어요."),
            new Scenario("비정상 종료 복구","LKS-GEN-1008","Initial","1634:1622","KSampler","이전 생성 중 ComfyUI 또는 LAKIS가 비정상 종료됐어요."),
            new Scenario("작업 진행 멈춤","LKS-GEN-1009","Initial","1634:1622","KSampler","ComfyUI 작업이 진행되지 않아 생성을 중단했어요."),
            new Scenario("시드 범위 오류","LKS-GEN-1101","요청 검증","", "", "시드 값이 지원 범위를 벗어났어요."),
            new Scenario("프롬프트 인코딩","LKS-GEN-1201","프롬프트","2133","EasyUseAnimaPromptStudioAdvanced","프롬프트를 인코딩하지 못했어요."),
            new Scenario("Initial 샘플링","LKS-GEN-1301","Initial","1634:1622","KSampler","Initial 샘플링 단계에서 오류가 발생했어요."),
            new Scenario("Initial 디코딩","LKS-GEN-1302","Initial Decode","1635","VAEDecode","Initial 이미지 디코딩에 실패했어요."),
            new Scenario("HighRez 인코딩","LKS-GEN-1401","HighRez Encode","1633:1794","VAEEncode","HighRez 이미지 인코딩에 실패했어요."),
            new Scenario("HighRez 샘플링","LKS-GEN-1402","HighRez","1633:1612","KSampler","HighRez 샘플링에 실패했어요."),
            new Scenario("HighRez 디코딩","LKS-GEN-1403","HighRez Decode","1633:1790","VAEDecode","HighRez 이미지 디코딩에 실패했어요."),
            new Scenario("얼굴 디테일","LKS-GEN-1501","Face Detail","1530:1826","DetailerForEach","얼굴 디테일 처리에 실패했어요."),
            new Scenario("눈 디테일","LKS-GEN-1502","Eye Detail","1836:2069","DetailerForEach","눈 디테일 처리에 실패했어요."),
            new Scenario("업스케일","LKS-GEN-1601","Upscale","1541:1538","UltimateSDUpscale","업스케일 단계에서 오류가 발생했어요."),
            new Scenario("최종 저장","LKS-GEN-1701","Final Save","775","Image Saver","완성된 이미지를 저장하지 못했어요."),
            new Scenario("체크포인트 로딩","LKS-MOD-1001","모델 로딩","890:1365","DiffusionModelLoaderKJ","체크포인트를 불러오지 못했어요."),
            new Scenario("VAE 로딩","LKS-MOD-1002","모델 로딩","890:159","VAELoader","VAE를 불러오지 못했어요."),
            new Scenario("CLIP 로딩","LKS-MOD-1003","모델 로딩","890:164","CLIPLoader","CLIP을 불러오지 못했어요."),
            new Scenario("체크포인트 없음","LKS-MOD-1101","요청 검증","", "", "선택한 체크포인트가 없어요."),
            new Scenario("체크포인트 비호환","LKS-MOD-1102","요청 검증","", "", "체크포인트가 LAKIS와 호환되지 않아요."),
            new Scenario("VAE 없음","LKS-MOD-1103","요청 검증","", "", "선택한 VAE가 없어요."),
            new Scenario("CLIP 없음","LKS-MOD-1104","요청 검증","", "", "선택한 CLIP이 없어요."),
            new Scenario("LoRA 없음","LKS-MOD-1201","요청 검증","", "", "선택한 LoRA가 없어요."),
            new Scenario("i2i 이미지 로딩","LKS-I2I-1001","i2i Load","1744","LoadImage","i2i 이미지를 불러오지 못했어요."),
            new Scenario("i2i 크기 변환","LKS-I2I-1002","i2i Resize","1736:1741","ImageScale","i2i 이미지 크기 변환에 실패했어요."),
            new Scenario("i2i 파일 누락","LKS-I2I-1101","요청 검증","", "", "i2i 입력 이미지를 다시 선택해 주세요."),
            new Scenario("샘플러 설정 오류","LKS-CFG-1101","요청 검증","", "", "지원하지 않는 샘플러입니다."),
            new Scenario("스케줄러 설정 오류","LKS-CFG-1102","요청 검증","", "", "지원하지 않는 스케줄러입니다."),
            new Scenario("세부 설정 오류","LKS-CFG-1103","요청 검증","", "", "세부 설정값이 올바르지 않아요."),
        };
    }

    private static string Json(string value)
    {
        if (value == null) return "null";
        return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"")
            .Replace("\r", "\\r").Replace("\n", "\\n") + "\"";
    }

    private static string BuildPayload(string code, string stage, string nodeId,
                                       string nodeType, string message)
    {
        string request = "devtest-" + Guid.NewGuid().ToString("N");
        string settingDiagnostic = code == "LKS-CFG-1103"
            ? "{\"setting_node_id\":\"890:905\",\"setting_node_type\":\"SamplerConfig\"," +
              "\"setting_name\":\"cfg\",\"received_value\":125," +
              "\"node_declaration\":{\"min\":0,\"max\":100,\"step\":0.1}," +
              "\"internal_reason\":\"890:905.cfg exceeds the node-declared maximum\"}"
            : "null";
        return "{" + "\"message\":" + Json(message) + "," +
            "\"error_code\":" + Json(code) + ",\"error_stage\":" + Json(stage) + "," +
            "\"error_node_id\":" + Json(nodeId) + ",\"error_node_type\":" + Json(nodeType) + "," +
            "\"error_exception_type\":\"DevelopmentSimulatedError\"," +
            "\"request_id\":" + Json(request) + ",\"prompt_id\":null," +
            "\"setting_diagnostic\":" + settingDiagnostic + "," +
            "\"diagnostic_context\":{" +
            "\"generation\":{\"mode\":\"fast\"}," +
            "\"model\":{\"checkpoint\":\"novaAnimeAM_test.safetensors\",\"vae\":\"qwen_image_vae.safetensors\",\"clip\":\"qwen_3_06b_base.safetensors\",\"sampler\":\"euler_ancestral\",\"scheduler\":\"normal\",\"steps\":30,\"cfg\":5}," +
            "\"output\":{\"width\":1024,\"height\":1536,\"aspect_locked\":true}," +
            "\"loras_enabled\":true,\"loras\":[]," +
            "\"camera\":{\"enabled\":true,\"pos_x\":0,\"pos_y\":0,\"pos_z\":0.7,\"roll\":0,\"frame_y\":0}," +
            "\"i2i\":{\"enabled\":false,\"denoise\":0.5},\"advanced_node_settings\":{}}}";
    }

    internal void PositionNextTo(Form owner)
    {
        Rectangle work = Screen.FromControl(owner).WorkingArea;
        int x = owner.Right + 10;
        if (x + Width > work.Right) x = Math.Max(work.Left, owner.Left - Width - 10);
        int y = Math.Max(work.Top, Math.Min(owner.Top, work.Bottom - Height));
        Location = new Point(x, y);
    }
}
#endif
