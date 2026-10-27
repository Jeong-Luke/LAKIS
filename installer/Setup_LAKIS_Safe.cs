using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Web.Script.Serialization;

// Opt into modern System.IO handling before the first framework path lookup.
[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.6.2")]

internal sealed class DownloadItem
{
    internal string Name, Url, Sha, Destination;
    internal long Bytes;
    internal DownloadItem(string name, string url, string sha, string destination = null, long bytes = 0)
    { Name = name; Url = url; Sha = sha; Destination = destination; Bytes = bytes; }
}

internal sealed class OptionalModelForm : Form
{
    private readonly RadioButton defaultOnly = new RadioButton();
    private readonly RadioButton includeAnimeSharp = new RadioButton();
    private readonly CheckBox acknowledgement = new CheckBox();
    private readonly Button next = new Button();

    internal bool IncludeAnimeSharp { get { return includeAnimeSharp.Checked; } }

    internal OptionalModelForm()
    {
        Text = "LAKIS 선택 모델 추가";
        ClientSize = new Size(720, 470);
        StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false; MinimizeBox = false;
        BackColor = Color.FromArgb(12, 14, 22);
        ForeColor = Color.FromArgb(225, 229, 255);
        Font = new Font("Segoe UI", 10F);

        Controls.Add(new Label { Left=30, Top=25, Width=650, Height=35,
            Text="업스케일 모델 선택", Font=new Font("Segoe UI",18F,FontStyle.Bold),
            ForeColor=Color.FromArgb(151,112,255) });
        Controls.Add(new Label { Left=31, Top=67, Width=650, Height=42,
            Text="기본 모델은 상업적 작업에도 사용할 수 있습니다. 필요한 경우에만 비상업용 모델을 추가하세요.",
            ForeColor=Color.FromArgb(151,160,185) });

        defaultOnly.SetBounds(38, 128, 620, 74);
        defaultOnly.Text="RealESRGAN Anime 6B  ·  기본 추천  ·  BSD-3-Clause\n상업적 이용 가능한 공식 애니메이션 특화 모델만 설치합니다.";
        defaultOnly.Checked=true; defaultOnly.Padding=new Padding(14,0,0,0);
        defaultOnly.Appearance=Appearance.Button; defaultOnly.FlatStyle=FlatStyle.Flat;
        defaultOnly.FlatAppearance.BorderColor=Color.FromArgb(143,107,255);
        defaultOnly.BackColor=Color.FromArgb(25,23,43); defaultOnly.ForeColor=Color.FromArgb(225,229,255);

        includeAnimeSharp.SetBounds(38, 216, 620, 74);
        includeAnimeSharp.Text="AnimeSharp V4 Fast를 기본으로 사용  ·  CC BY-NC-SA 4.0\nRealESRGAN도 함께 설치되어 나중에 다시 선택할 수 있습니다.";
        includeAnimeSharp.Padding=new Padding(14,0,0,0);
        includeAnimeSharp.Appearance=Appearance.Button; includeAnimeSharp.FlatStyle=FlatStyle.Flat;
        includeAnimeSharp.FlatAppearance.BorderColor=Color.FromArgb(74,82,108);
        includeAnimeSharp.BackColor=Color.FromArgb(23,28,41); includeAnimeSharp.ForeColor=Color.FromArgb(255,153,195);

        acknowledgement.SetBounds(52, 307, 590, 45);
        acknowledgement.Text="AnimeSharp는 상업적 이용이 허용되지 않으며 CC BY-NC-SA 4.0 조건이 적용됨을 확인했습니다.";
        acknowledgement.ForeColor=Color.FromArgb(255,153,195); acknowledgement.Enabled=false;
        acknowledgement.CheckedChanged += delegate { RefreshState(); };
        includeAnimeSharp.CheckedChanged += delegate { acknowledgement.Enabled=includeAnimeSharp.Checked; if(!includeAnimeSharp.Checked)acknowledgement.Checked=false; RefreshState(); };
        defaultOnly.CheckedChanged += delegate { RefreshState(); };

        var licence = new LinkLabel { Left=52, Top=357, Width=350, Height=24,
            Text="원 배포 페이지 및 라이선스 확인", LinkColor=Color.FromArgb(124,211,255),
            ActiveLinkColor=Color.FromArgb(184,168,255), VisitedLinkColor=Color.FromArgb(124,211,255) };
        licence.LinkClicked += delegate { Process.Start("https://huggingface.co/Kim2091/2x-AnimeSharpV4"); };
        var back = new Button { Left=456, Top=397, Width=95, Height=42, Text="취소", DialogResult=DialogResult.Cancel };
        next.SetBounds(562,397,96,42); next.Text="다음"; next.DialogResult=DialogResult.OK;
        foreach(Button button in new[]{back,next}) { button.FlatStyle=FlatStyle.Flat; button.FlatAppearance.BorderSize=0; button.ForeColor=Color.White; button.BackColor=Color.FromArgb(92,69,199); }
        AcceptButton=next; CancelButton=back;
        Controls.AddRange(new Control[]{defaultOnly,includeAnimeSharp,acknowledgement,licence,back,next});
        RefreshState();
    }

    private void RefreshState()
    {
        next.Enabled=defaultOnly.Checked || (includeAnimeSharp.Checked && acknowledgement.Checked);
        defaultOnly.FlatAppearance.BorderColor=defaultOnly.Checked?Color.FromArgb(143,107,255):Color.FromArgb(74,82,108);
        includeAnimeSharp.FlatAppearance.BorderColor=includeAnimeSharp.Checked?Color.FromArgb(255,126,182):Color.FromArgb(74,82,108);
    }
}

internal sealed class SafeSetupForm : Form
{
    private readonly TextBox destination = new TextBox();
    private readonly Label status = new Label();
    private readonly LakisProgressBar progress = new LakisProgressBar();
    private readonly Button install = new Button();
    private readonly Button repair = new Button();
    private readonly CheckBox launch = new CheckBox();
    private readonly CenterCropPictureBox artwork = new CenterCropPictureBox();
    private readonly List<Image> artworkFrames = new List<Image>();
    private readonly Timer artworkTimer = new Timer();
    private int artworkIndex;
    private readonly Button closeButton = new Button();

    internal SafeSetupForm()
    {
        Text = "LAKIS 설치"; ClientSize = new Size(760,430); FormBorderStyle = FormBorderStyle.None;
        MaximizeBox = false; StartPosition = FormStartPosition.CenterScreen;
        BackColor=Color.FromArgb(12,14,22);ForeColor=Color.White;Font=new Font("Segoe UI",10F);DoubleBuffered=true;
        LakisWindowDrag.Enable(this);
        LoadArtwork();artwork.SetBounds(400,48,336,358);artwork.BackColor=Color.FromArgb(18,22,38);
        if(artworkFrames.Count>0)artwork.Image=artworkFrames[0];artworkTimer.Interval=5000;artworkTimer.Tick+=(_,__)=>{if(artworkFrames.Count<2)return;artworkIndex=(artworkIndex+1)%artworkFrames.Count;artwork.Image=artworkFrames[artworkIndex];};artworkTimer.Start();
        var logo=new PictureBox{Left=42,Top=35,Width=48,Height=48,SizeMode=PictureBoxSizeMode.Zoom,Image=Icon.ExtractAssociatedIcon(Application.ExecutablePath).ToBitmap()};
        Controls.Add(new Label { Left=104,Top=36,Width=265,Height=32,Text="L A K I S",Font=new Font("Segoe UI",19,FontStyle.Bold),ForeColor=Color.FromArgb(225,229,255) });
        Controls.Add(new Label { Left=106,Top=70,Width=245,Height=24,Text="Studio",Font=new Font("Segoe UI",10,FontStyle.Bold),ForeColor=Color.FromArgb(171,178,203) });
        Controls.Add(new Label { Left=43,Top=111,Width=315,Height=38,Text="공식 배포처의 검증된 구성요소를 설치합니다.\n최소 15GB의 여유 공간이 필요합니다.",ForeColor=Color.FromArgb(132,141,165),Font=new Font("Segoe UI",8.5F) });
        Controls.Add(new Label { Left=43,Top=158,Width=100,Text="설치 위치",ForeColor=Color.FromArgb(184,168,255) });
        destination.SetBounds(43,181,315,27);destination.BackColor=Color.FromArgb(19,23,34);destination.ForeColor=Color.White;destination.BorderStyle=BorderStyle.FixedSingle;
        destination.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","LAKIS");
        progress.SetBounds(43,228,315,7); progress.Minimum=0; progress.Maximum=100;
        status.SetBounds(43,250,315,34); status.Text="설치 준비 완료";status.ForeColor=Color.FromArgb(184,168,255);
        launch.SetBounds(43,286,230,25); launch.Text="설치 후 LAKIS 실행"; launch.Checked=true;
        repair.SetBounds(43,337,145,38); repair.Text="기존 설치 복구"; repair.Click += async (_,__) => await RepairAsync();
        install.SetBounds(201,337,157,38); install.Text="새로 설치"; install.Click += async (_,__) => await InstallAsync();
        foreach(Button button in new[]{repair,install}){button.FlatStyle=FlatStyle.Flat;button.FlatAppearance.BorderSize=0;button.BackColor=Color.FromArgb(111,82,225);button.ForeColor=Color.White;button.Font=new Font("Segoe UI",9F,FontStyle.Bold);button.Cursor=Cursors.Hand;}
        var copyright=new Label{Left=43,Top=399,Width=335,Height=18,Text="© 2026 Luke Jeong. All rights reserved. · LAKIS v8.0.0",ForeColor=Color.FromArgb(104,112,137),Font=new Font("Segoe UI",8F)};
        ConfigureCloseButton();
        Controls.AddRange(new Control[]{artwork,logo,destination,progress,status,launch,repair,install,copyright,closeButton});
        closeButton.BringToFront();
        destination.TextChanged+=(_,__)=>RefreshDestinationMode();
        Shown+=(_,__)=>RefreshDestinationMode();
        FormClosed+=(_,__)=>{artworkTimer.Stop();foreach(Image frame in artworkFrames)frame.Dispose();};
    }

    private void ConfigureCloseButton()
    {
        closeButton.SetBounds(ClientSize.Width-48,0,48,42);
        closeButton.Text="\uE8BB";
        closeButton.Font=new Font("Segoe MDL2 Assets",9F);
        closeButton.ForeColor=Color.FromArgb(205,211,225);
        closeButton.BackColor=Color.Transparent;
        closeButton.FlatStyle=FlatStyle.Flat;
        closeButton.FlatAppearance.BorderSize=0;
        closeButton.FlatAppearance.MouseOverBackColor=Color.FromArgb(196,43,28);
        closeButton.TabStop=false;
        closeButton.Cursor=Cursors.Hand;
        closeButton.Anchor=AnchorStyles.Top|AnchorStyles.Right;
        closeButton.Click+=(_,__)=>Close();
    }

    private void LoadArtwork()
    {
        Assembly assembly=Assembly.GetExecutingAssembly();
        foreach(string name in new[]{"LAKIS.Splash1","LAKIS.Splash2"})using(Stream stream=assembly.GetManifestResourceStream(name))if(stream!=null)artworkFrames.Add(new Bitmap(stream));
    }

    private void SetActionButtonsVisible(bool visible)
    {
        install.Visible=visible;
        repair.Visible=visible;
        if(visible)RefreshDestinationMode();
        else{install.Enabled=false;repair.Enabled=false;}
    }

    private void RefreshDestinationMode()
    {
        string target;
        try{target=Path.GetFullPath(destination.Text.Trim());}
        catch{install.Enabled=false;repair.Enabled=false;status.Text="설치 위치를 확인해 주세요";return;}
        if(SafeInstaller.IsExistingInstallation(target))
        {
            install.Enabled=false;repair.Enabled=true;
            repair.BackColor=Color.FromArgb(208,72,137);
            status.Text="기존 LAKIS 감지 · '기존 설치 복구'를 사용하세요";
            return;
        }
        repair.BackColor=Color.FromArgb(111,82,225);
        repair.Enabled=false;
        if(SafeInstaller.HasDirectoryEntries(target))
        {
            install.Enabled=false;
            status.Text="비어 있지 않은 폴더입니다 · 빈 설치 위치를 선택하세요";
        }
        else
        {
            install.Enabled=true;
            status.Text="설치 준비 완료";
        }
    }

    private async Task InstallAsync()
    {
        string target;
        try { target = Path.GetFullPath(destination.Text.Trim()); }
        catch { MessageBox.Show("설치 위치가 올바르지 않습니다."); return; }
        if (target.Length < 8) { MessageBox.Show("설치 위치가 너무 넓습니다."); return; }
        if(SafeInstaller.IsExistingInstallation(target))
        {
            MessageBox.Show("이 위치에 기존 LAKIS 설치가 있습니다.\n\n사용자 이미지, 워크플로와 설정을 보존하려면 '기존 설치 복구'를 사용해 주세요.","기존 LAKIS 설치 감지",MessageBoxButtons.OK,MessageBoxIcon.Information);
            RefreshDestinationMode();repair.Select();return;
        }
        if(SafeInstaller.HasDirectoryEntries(target))
        {
            MessageBox.Show("새 설치는 비어 있는 폴더에만 진행할 수 있습니다.\n기존 파일을 보호하기 위해 이 폴더를 삭제하거나 덮어쓰지 않았습니다.","설치 위치 보호",MessageBoxButtons.OK,MessageBoxIcon.Warning);
            RefreshDestinationMode();return;
        }
        var drive = new DriveInfo(Path.GetPathRoot(target));
        if (drive.AvailableFreeSpace < 15L*1024*1024*1024) { MessageBox.Show("최소 15GB의 여유 공간이 필요합니다."); return; }
        bool addAnimeSharp;
        using(var options=new OptionalModelForm())
        {
            if(options.ShowDialog(this)!=DialogResult.OK)return;
            addAnimeSharp=options.IncludeAnimeSharp;
        }
        SetActionButtonsVisible(false); destination.Enabled=false;
        try
        {
            await Task.Run(() => SafeInstaller.Install(target, addAnimeSharp, line => BeginInvoke((Action)(() => {
                status.Text=line; if(line.IndexOf('%')<0&&progress.Value<95) progress.Value++;
            }))));
            progress.Value=100; status.Text="설치 완료";
            MessageBox.Show("LAKIS 설치가 완료되었습니다.","LAKIS",MessageBoxButtons.OK,MessageBoxIcon.Information);
            if(launch.Checked) Process.Start(Path.Combine(target,"LAKIS.exe"));
            Close();
        }
        catch(Exception error)
        {
            SetActionButtonsVisible(true); destination.Enabled=true; status.Text="설치 실패";
            MessageBox.Show(error.Message,"LAKIS 설치 오류",MessageBoxButtons.OK,MessageBoxIcon.Error);
        }
    }

    private async Task RepairAsync()
    {
        string target;try{target=Path.GetFullPath(destination.Text.Trim());}catch{MessageBox.Show("설치 위치가 올바르지 않습니다.");return;}
        SetActionButtonsVisible(false);destination.Enabled=false;
        try{await Task.Run(()=>SafeInstaller.Repair(target,line=>BeginInvoke((Action)(()=>{status.Text=line;if(progress.Value<95)progress.Value++;}))));progress.Value=100;status.Text="복구 완료";MessageBox.Show("기존 LAKIS 설치 복구가 완료되었습니다.","LAKIS",MessageBoxButtons.OK,MessageBoxIcon.Information);if(launch.Checked)Process.Start(Path.Combine(target,"LAKIS.exe"));Close();}
        catch(Exception error){SetActionButtonsVisible(true);destination.Enabled=true;status.Text="복구 실패";MessageBox.Show(error.Message,"LAKIS 복구 오류",MessageBoxButtons.OK,MessageBoxIcon.Error);}
    }

    [STAThread] private static int Main(string[] args)
    {
        string target = null;
        for(int i=0;i+1<args.Length;i++) if(args[i]=="--install-dir") target=args[i+1];
        if(Array.Exists(args,a=>a=="--headless"))
        {
            try { if(String.IsNullOrWhiteSpace(target)) return 2;if(Array.Exists(args,a=>a=="--repair"))SafeInstaller.Repair(Path.GetFullPath(target),Console.WriteLine);else SafeInstaller.Install(Path.GetFullPath(target),Array.Exists(args,a=>a=="--include-noncommercial-upscaler"),Console.WriteLine); return 0; }
            catch(Exception error) { Console.Error.WriteLine(error); return 1; }
        }
        Application.EnableVisualStyles(); Application.Run(new SafeSetupForm()); return 0;
    }
}

internal static class SafeInstaller
{
    private const string Revision = "v7.5.3";
    // The release build injects the hash of the exact commit archive.
    private const string SourceArchiveSha256 = "BUILD_REQUIRES_PINNED_SOURCE_SHA256";
    private const string WebView2BootstrapperUrl = "BUILD_REQUIRES_PINNED_WEBVIEW2_URL";
    private const string WebView2BootstrapperSha256 = "BUILD_REQUIRES_PINNED_WEBVIEW2_SHA256";
    private const long WebView2BootstrapperBytes = 0;
    private const string ReleaseVersion = "8.0.0";
    private static readonly DownloadItem Portable = new DownloadItem("ComfyUI v0.21.1",
        "https://github.com/Comfy-Org/ComfyUI/releases/download/v0.21.1/ComfyUI_windows_portable_nvidia.7z",
        "7C380D4309BBDA395366C49564EDF8996181FD45E61B6F353EA417F32BC3B970",null,2001582790);

    internal static void Install(string target, bool includeAnimeSharp, Action<string> report)
    {
        target=Path.GetFullPath(target);
        ValidateFreshTarget(target);
        string manifest=ReadRuntimeInstallManifest();
        var log=new List<string>();
        Action<string> status=s=>{lock(log)log.Add(s);report(s);};
        PrepareTarget(target,status);
        try
        {
            string cache=InstallerCache();
            StopOwned(target);
            RunRuntimeInstaller(manifest,target,cache,"fresh",includeAnimeSharp,status);
            try { CreateDesktopShortcut(target,status); }
            catch(Exception error) { status("설치는 완료되었지만 바로가기를 만들지 못했습니다: " + error.Message); }
            File.WriteAllLines(Path.Combine(target,"network-install.log"),log.ToArray());
            status("설치 완료");
        }
        catch(Exception error)
        {
            throw RuntimeFailure("설치",error,log);
        }
    }

    private static InvalidOperationException RuntimeFailure(string operation,Exception error,List<string> log)
    {
        string detail;
        try
        {
            lock(log)log.Add("FAILURE: "+error.GetType().Name+": "+error.Message);
            string path=UniqueScratch(InstallerCache(),"runtime-failure")+".log";
            RejectReparsePath(path);
            using(var output=new StreamWriter(new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.Read)))
                foreach(string line in log)output.WriteLine(line);
            detail="로그: "+path;
        }
        catch(Exception logError){detail="실패 로그 저장 오류: "+logError.Message;}
        return new InvalidOperationException(operation+" 중 오류가 발생했습니다.\n"+
            error.GetType().Name+": "+error.Message+"\n\n"+detail,error);
    }

    internal static void InstallFresh(string target, Action<string> build, Action<string> report)
    {
        target=Path.GetFullPath(target);
        var parent=Directory.GetParent(target);
        if(parent==null)throw new InvalidOperationException("드라이브 최상위 경로에는 설치할 수 없습니다. 새 하위 폴더를 선택하세요.");
        PrepareTarget(target,report);
        string stage=Path.Combine(parent.FullName,".LAKIS-setup-stage-"+Guid.NewGuid().ToString("N"));
        // Build beside the target, then promote on the same volume. Never
        // delete a non-empty target, even if another process changed it.
        try
        {
            build(stage);
            PrepareTarget(target,report);
            Directory.Delete(target,false);
            Directory.Move(stage,target);
        }
        catch(Exception error)
        {
            throw new InvalidOperationException("설치가 중단되었습니다. 임시 폴더: "+stage+"\n"+error.Message,error);
        }
    }

    private static void ValidateFreshTarget(string target)
    {
        if(Directory.GetParent(target)==null)
            throw new InvalidOperationException("드라이브 최상위 경로에는 설치할 수 없습니다. 새 하위 폴더를 선택하세요.");
        RejectReparsePath(target);
        if(IsExistingInstallation(target))
            throw new InvalidOperationException("기존 LAKIS 설치가 감지되었습니다. 사용자 데이터를 보존하려면 새 설치 대신 '기존 설치 복구'를 사용하세요.");
        if(HasDirectoryEntries(target))
            throw new InvalidOperationException("설치 폴더가 비어 있지 않습니다. 기존 파일 보호를 위해 새 설치를 중단했습니다. 비어 있는 폴더를 선택하세요.");
    }

    private static string ReadRuntimeInstallManifest()
    {
        string json;
        using(Stream input=Assembly.GetExecutingAssembly().GetManifestResourceStream("LAKIS.RuntimeInstallManifest"))
        {
            if(input==null)throw new InvalidDataException("내장 런타임 설치 manifest가 없습니다.");
            using(var reader=new StreamReader(input,new System.Text.UTF8Encoding(false,true),true))
                json=reader.ReadToEnd();
        }
        if(String.IsNullOrWhiteSpace(json))throw new InvalidDataException("내장 런타임 설치 manifest가 비어 있습니다.");
        Dictionary<string,object> manifest;
        try
        {
            var serializer=new JavaScriptSerializer { MaxJsonLength=Int32.MaxValue, RecursionLimit=128 };
            manifest=serializer.Deserialize<Dictionary<string,object>>(json);
        }
        catch(Exception error)
        {
            throw new InvalidDataException("내장 런타임 설치 manifest가 올바른 JSON이 아닙니다.",error);
        }
        if(manifest==null)throw new InvalidDataException("내장 런타임 설치 manifest가 객체가 아닙니다.");
        if(RequiredInteger(manifest,"schema")!=1)
            throw new InvalidDataException("지원하지 않는 런타임 설치 manifest schema입니다.");
        if(!String.Equals(RequiredString(manifest,"version"),ReleaseVersion,StringComparison.Ordinal))
            throw new InvalidDataException("내장 런타임 설치 manifest 버전은 "+ReleaseVersion+"이어야 합니다.");
        ValidateSimpleDownload(RequiredObject(manifest,"base"),"base");
        ValidateSimpleDownload(RequiredObject(manifest,"webview2"),"webview2");
        ValidateRuntimeBundle(RequiredObject(manifest,"runtime_bundle"));
        ValidateModelList(RequiredList(manifest,"models"),"models",false);
        ValidateModelList(RequiredList(manifest,"optional_animesharp"),"optional_animesharp",true);
        return json;
    }

    private static Dictionary<string,object> RequiredObject(Dictionary<string,object> owner,string name)
    {
        object value;
        if(!owner.TryGetValue(name,out value)||!(value is Dictionary<string,object>))
            throw new InvalidDataException("내장 런타임 설치 manifest 필드가 올바르지 않습니다: "+name);
        return (Dictionary<string,object>)value;
    }

    private static IList RequiredList(Dictionary<string,object> owner,string name)
    {
        object value;
        if(!owner.TryGetValue(name,out value)||!(value is IList))
            throw new InvalidDataException("내장 런타임 설치 manifest 필드가 올바르지 않습니다: "+name);
        return (IList)value;
    }

    private static string RequiredString(Dictionary<string,object> owner,string name)
    {
        object value;
        if(!owner.TryGetValue(name,out value)||!(value is string)||String.IsNullOrWhiteSpace((string)value))
            throw new InvalidDataException("내장 런타임 설치 manifest 필드가 올바르지 않습니다: "+name);
        return (string)value;
    }

    private static long RequiredInteger(Dictionary<string,object> owner,string name)
    {
        object value;
        long result;
        if(!owner.TryGetValue(name,out value)||!TryReadInteger(value,out result))
            throw new InvalidDataException("내장 런타임 설치 manifest 숫자 필드가 올바르지 않습니다: "+name);
        return result;
    }

    private static bool TryReadInteger(object value,out long result)
    {
        if(value is int){result=(int)value;return true;}
        if(value is long){result=(long)value;return true;}
        result=0;return false;
    }

    private static void ValidateSimpleDownload(Dictionary<string,object> item,string label)
    {
        string name=RequiredString(item,"name");
        string url=RequiredString(item,"url");
        string digest=RequiredString(item,"sha256");
        if(name.IndexOfAny(new[]{'/', '\\', ':'})>=0||
           !url.StartsWith("https://",StringComparison.OrdinalIgnoreCase)||
           !System.Text.RegularExpressions.Regex.IsMatch(digest,"^[A-Fa-f0-9]{64}$")||
           RequiredInteger(item,"bytes")<=0)
            throw new InvalidDataException("내장 런타임 설치 manifest download 필드가 올바르지 않습니다: "+label);
    }

    private static void ValidateModelList(IList items,string label,bool single)
    {
        if((single&&items.Count!=5)||(!single&&items.Count==0))
            throw new InvalidDataException("내장 런타임 설치 manifest 모델 목록이 올바르지 않습니다: "+label);
        if(single){ValidateModel(items,label);return;}
        foreach(object item in items)ValidateModel(item,label);
    }

    private static void ValidateModel(object value,string label)
    {
        IList item=value as IList;
        long size;
        if(item==null||item.Count!=5||!(item[0] is string)||String.IsNullOrWhiteSpace((string)item[0])||
           !(item[1] is string)||!((string)item[1]).StartsWith("https://",StringComparison.OrdinalIgnoreCase)||
           !(item[2] is string)||!System.Text.RegularExpressions.Regex.IsMatch((string)item[2],"^[A-Fa-f0-9]{64}$")||
           !(item[3] is string)||String.IsNullOrWhiteSpace((string)item[3])||
           !TryReadInteger(item[4],out size)||size<=0)
            throw new InvalidDataException("내장 런타임 설치 manifest 모델 항목이 올바르지 않습니다: "+label);
    }

    private static void ValidateRuntimeBundle(Dictionary<string,object> bundle)
    {
        if(RequiredInteger(bundle,"schema")!=2||
           !String.Equals(RequiredString(bundle,"product"),"LAKIS",StringComparison.Ordinal)||
           !String.Equals(RequiredString(bundle,"version"),ReleaseVersion,StringComparison.Ordinal))
            throw new InvalidDataException("내장 런타임 bundle identity가 올바르지 않습니다.");
        string name=RequiredString(bundle,"name");
        if(!name.EndsWith(".zip",StringComparison.OrdinalIgnoreCase)||name.IndexOfAny(new[]{'/', '\\', ':'})>=0)
            throw new InvalidDataException("내장 런타임 bundle 이름이 올바르지 않습니다.");
        RequiredString(bundle,"comfyui_version");
        string archiveHash=RequiredString(bundle,"sha256");
        string manifestHash=RequiredString(bundle,"manifest_sha256");
        long archiveBytes=RequiredInteger(bundle,"bytes");
        if(!System.Text.RegularExpressions.Regex.IsMatch(archiveHash,"^[A-Fa-f0-9]{64}$")||
           !System.Text.RegularExpressions.Regex.IsMatch(manifestHash,"^[A-Fa-f0-9]{64}$")||
           archiveBytes<=0||RequiredInteger(bundle,"files")<=0||bundle.ContainsKey("url"))
            throw new InvalidDataException("내장 런타임 bundle fields가 올바르지 않습니다.");
        IList parts=RequiredList(bundle,"parts");
        if(parts.Count<1||parts.Count>999)throw new InvalidDataException("내장 런타임 bundle parts가 올바르지 않습니다.");
        long total=0;
        for(int index=1;index<=parts.Count;index++)
        {
            Dictionary<string,object> part=parts[index-1] as Dictionary<string,object>;
            if(part==null)throw new InvalidDataException("내장 런타임 bundle part가 객체가 아닙니다.");
            string expectedName=name+".part"+index.ToString("D3");
            string partName=RequiredString(part,"name");
            string partHash=RequiredString(part,"sha256");
            string partUrl=RequiredString(part,"url");
            long bytes=RequiredInteger(part,"bytes");
            if(!String.Equals(partName,expectedName,StringComparison.Ordinal)||
               !System.Text.RegularExpressions.Regex.IsMatch(partHash,"^[A-Fa-f0-9]{64}$")||
               bytes<=0||bytes>1024L*1024*1024||
               !String.Equals(partUrl,"https://github.com/Jeong-Luke/LAKIS/releases/download/v"+
                   ReleaseVersion+"/"+expectedName,StringComparison.Ordinal)||
               total>Int64.MaxValue-bytes)
                throw new InvalidDataException("내장 런타임 bundle part가 올바르지 않습니다.");
            total+=bytes;
        }
        if(total!=archiveBytes)throw new InvalidDataException("내장 런타임 bundle 크기가 parts와 일치하지 않습니다.");
    }

    private static string PrepareBootstrapPython(string cache,Action<string> status,out string workspace)
    {
        ServicePointManager.SecurityProtocol=(SecurityProtocolType)3072;
        ServicePointManager.DefaultConnectionLimit=8;
        string archive=Fetch(Portable,cache,status);
        status("ComfyUI bootstrap Python 압축 해제");
        workspace=UniqueScratch(cache,"runtime-bootstrap");
        RejectReparsePath(workspace);
        Reset(workspace);
        Extract7z(archive,workspace);
        string python=Path.Combine(workspace,"ComfyUI_windows_portable","python_embeded","python.exe");
        RejectReparsePath(python);
        if(!File.Exists(python))throw new InvalidDataException("ComfyUI bootstrap Python을 찾을 수 없습니다.");
        return python;
    }

    private static void RunRuntimeInstaller(string manifest,string target,string cache,string mode,
        bool includeAnimeSharp,Action<string> status)
    {
        string workspace=null;
        bool complete=false;
        try
        {
            string python=PrepareBootstrapPython(cache,status,out workspace);
            RuntimeBundleInstaller.Install(python,manifest,target,cache,mode,includeAnimeSharp,status);
            complete=true;
        }
        finally
        {
            if(!String.IsNullOrEmpty(workspace)&&Directory.Exists(workspace))
            {
                if(complete)
                    try{DeleteTree(workspace);}
                    catch(Exception error){status("Bootstrap 임시 폴더를 정리하지 못했습니다: "+workspace+" | "+error.Message);}
                else status("실패 확인을 위해 Bootstrap 임시 폴더를 보존합니다: "+workspace);
            }
        }
    }

    internal static void Repair(string target,Action<string> report)
    {
        target=Path.GetFullPath(target);
        foreach(string relative in new[]{"", "ComfyUI/custom_nodes", "ComfyUI/LAKIS/workflows", "third_party_licenses", "ComfyUI/models/upscale_models", ".lakis", "VERSION", "repair.log", "python_embeded", "python_embeded/python.exe"})
            RejectReparsePath(Path.Combine(target,relative));
        string comfy=Path.Combine(target,"ComfyUI");
        if(!IsExistingInstallation(target)||!Directory.Exists(comfy))
            throw new InvalidOperationException("완료된 LAKIS 설치를 찾을 수 없습니다. 설치 위치를 확인하거나 새로 설치를 선택하세요.");
        string installedVersion=File.ReadAllText(Path.Combine(target,"VERSION")).Trim();
        if(!String.Equals(installedVersion,ReleaseVersion,StringComparison.Ordinal))
            throw new InvalidOperationException("이 복구는 LAKIS "+ReleaseVersion+" 설치에만 적용할 수 있습니다. 기존 설치를 변경하지 않았습니다.");
        string manifest=ReadRuntimeInstallManifest();
        var log=new List<string>();
        Action<string> status=s=>{lock(log)log.Add(s);report(s);};
        try
        {
            StopOwned(target);
            string cache=InstallerCache();
            RunRuntimeInstaller(manifest,target,cache,"repair",false,status);
            CreateDesktopShortcut(target,status);
            File.WriteAllLines(Path.Combine(target,"repair.log"),log.ToArray());
            status("복구 완료");
        }
        catch(Exception error)
        {
            throw RuntimeFailure("복구",error,log);
        }
    }
    private static string Fetch(DownloadItem item,string cache,Action<string> status)
    {
        string path=CachePath(cache,item), part=path+".part";
        using(var cacheLock=AcquireCacheLock(path,item.Name,status))
        {
        if(File.Exists(path)&&(item.Bytes>0&&new FileInfo(path).Length!=item.Bytes ||
           item.Sha.Length>0&&!String.Equals(HashWithRetry(path,item.Name),item.Sha,StringComparison.OrdinalIgnoreCase)))File.Delete(path);
        if(!File.Exists(path)&&File.Exists(part))
        {
            long size=new FileInfo(part).Length;
            if((item.Bytes<=0||size==item.Bytes)&&item.Sha.Length>0&&String.Equals(HashWithRetry(part,item.Name),item.Sha,StringComparison.OrdinalIgnoreCase))
                PromoteVerifiedPartial(part,path,item.Name,item.Sha,item.Bytes);
            else if(item.Bytes>0&&size>=item.Bytes)File.Delete(part);
        }
        if(!File.Exists(path))Download(item.Url,path,item.Name,item.Bytes,status);
        if(!File.Exists(path)&&File.Exists(part))
        {
            if(item.Bytes>0&&new FileInfo(part).Length!=item.Bytes)throw new IOException("CACHE_SIZE_FAILED: "+item.Name);
            status("다운로드 검증: "+item.Name);
            string actual;
            actual=HashWithRetry(part,item.Name);
            if(item.Sha.Length>0&&!String.Equals(actual,item.Sha,StringComparison.OrdinalIgnoreCase)){File.Delete(part);throw new IOException("SHA-256 검증 실패: "+item.Name);}
            PromoteVerifiedPartial(part,path,item.Name,item.Sha,item.Bytes);
            status("캐시 확정: "+item.Name);
        }
        if(item.Bytes>0&&new FileInfo(path).Length!=item.Bytes)throw new IOException("크기 검증 실패: "+item.Name);
        if(item.Sha.Length>0&&!String.Equals(HashWithRetry(path,item.Name),item.Sha,StringComparison.OrdinalIgnoreCase))throw new IOException("SHA-256 검증 실패: "+item.Name);
        return path;
        }
    }
    private static string CachePath(string cache,DownloadItem item)
    {
        if(!System.Text.RegularExpressions.Regex.IsMatch(item.Sha??"","^[a-fA-F0-9]{64}$"))throw new IOException("캐시 항목 SHA-256이 올바르지 않습니다: "+item.Name);
        var match=System.Text.RegularExpressions.Regex.Match(item.Name??"","(?i)\\.(zip|7z|exe|json|safetensors|pth|bin)$");
        string extension=match.Success?match.Value.ToLowerInvariant():".bin";
        return Path.Combine(cache,"a-"+item.Sha.ToUpperInvariant()+extension);
    }
    private static FileStream AcquireCacheLock(string path,string name,Action<string> status)
    {
        string lockPath=path+".lock";Directory.CreateDirectory(Path.GetDirectoryName(lockPath));DateTime deadline=DateTime.UtcNow.AddHours(4),notice=DateTime.MinValue;
        while(true)try{return new FileStream(lockPath,FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None);}catch(IOException error){if(!IsTransientFileError(error)||DateTime.UtcNow>=deadline)throw new IOException("CACHE_LOCK_FAILED: "+name+" | "+error.GetType().Name+" 0x"+error.HResult.ToString("X8")+" | "+lockPath,error);if((DateTime.UtcNow-notice).TotalSeconds>=5){status("다른 설치기가 캐시를 사용 중입니다: "+name);notice=DateTime.UtcNow;}System.Threading.Thread.Sleep(200);}
    }
    private static bool IsTransientFileError(Exception error){int code=error.HResult&0xFFFF;return code==32||code==33;}
    private static void PromoteVerifiedPartial(string part,string path,string name,string expectedHash,long expectedBytes)
    {
        Exception last=null;
        for(int attempt=1;attempt<=5;attempt++)try
        {
            if(File.Exists(path))
            {
                bool valid=(expectedBytes<=0||new FileInfo(path).Length==expectedBytes)&&String.Equals(HashWithRetry(path,name),expectedHash,StringComparison.OrdinalIgnoreCase);
                if(valid){if(File.Exists(part))File.Delete(part);return;}
                File.Replace(part,path,null,true);
            }
            else File.Move(part,path);
            return;
        }
        catch(Exception error)
        {
            last=error;if(!IsTransientFileError(error))throw new IOException("CACHE_PROMOTE_FAILED: "+name+" | "+error.GetType().Name+" 0x"+error.HResult.ToString("X8")+" | "+part,error);if(attempt<5)System.Threading.Thread.Sleep(attempt*200);
        }
        throw new IOException("CACHE_PROMOTE_FAILED: "+name+" | "+(last==null?"unknown":last.GetType().Name+" 0x"+last.HResult.ToString("X8"))+" | "+part,last);
    }
    private static void Download(string url,string path,string name,long expected,Action<string> status)
    {
        try { DownloadTransfer(url,path,name,expected,status); return; }
        catch(WebException error)
        {
            var response=error.Response as HttpWebResponse;
            if(response==null||response.StatusCode!=HttpStatusCode.RequestedRangeNotSatisfiable||!File.Exists(path+".part"))throw;
            response.Close();
        }
        catch(InvalidContentRangeException) { }
        if(File.Exists(path+".part"))File.Delete(path+".part");
        // One fresh transfer only; a second failure is reported.
        DownloadTransfer(url,path,name,expected,status);
    }
    private sealed class InvalidContentRangeException : IOException
    {
        internal InvalidContentRangeException() : base("DOWNLOAD_RANGE_INVALID: invalid Content-Range response") { }
    }
    private static long ValidateContentRange(string value,long start,long end,long expected,long contentLength)
    {
        var match=System.Text.RegularExpressions.Regex.Match(value??"","^bytes ([0-9]+)-([0-9]+)/([0-9]+)\\z");
        long actualStart,actualEnd,total;
        if(!match.Success||!Int64.TryParse(match.Groups[1].Value,out actualStart)||!Int64.TryParse(match.Groups[2].Value,out actualEnd)||!Int64.TryParse(match.Groups[3].Value,out total)||
            actualStart!=start||actualEnd<actualStart||actualEnd>=total||
            (end>=0?actualEnd!=end:actualEnd!=total-1)||
            (expected>0&&total!=expected)||
            (contentLength>=0&&contentLength!=actualEnd-actualStart+1))throw new InvalidContentRangeException();
        return total;
    }
    private static void DownloadTransfer(string url,string path,string name,long expected,Action<string> status)
    {
        ValidateDownloadOrigin(url,url);
        if(expected>=1024L*1024*1024&&!File.Exists(path+".part"))
        {
            try { DownloadParallel(url,path,name,expected,status); return; }
            catch(Exception error) { try{if(File.Exists(path+".part"))File.Delete(path+".part");}catch{}status("병렬 다운로드 재시도: "+name+" ("+error.Message+")"); }
        }
        string part=path+".part";
        long offset=File.Exists(part)?new FileInfo(part).Length:0;
        if(expected>0&&offset>expected){File.Delete(part);offset=0;}
        var request=(HttpWebRequest)WebRequest.Create(url);
        request.UserAgent="LAKIS-Installer/7.4.5";
        request.AllowAutoRedirect=true;
        if(offset>0)request.AddRange(offset);
        using(var response=(HttpWebResponse)request.GetResponse())
        {
            ValidateDownloadOrigin(url,response.ResponseUri.AbsoluteUri);
            bool resumed=response.StatusCode==HttpStatusCode.PartialContent;
            long rangeTotal=resumed?ValidateContentRange(response.Headers["Content-Range"],offset,-1,expected,response.ContentLength):0;
            if(offset>0&&!resumed)offset=0;
            long total=expected>0?expected:(resumed?rangeTotal:response.ContentLength);
            using(Stream input=response.GetResponseStream())
            using(var output=new FileStream(part,resumed?FileMode.Append:FileMode.Create,FileAccess.Write,FileShare.Read))
            {
                byte[] buffer=new byte[1024*1024];long received=offset,last=offset;
                var timer=Stopwatch.StartNew();long lastMs=0;int read;
                while((read=input.Read(buffer,0,buffer.Length))>0)
                {
                    output.Write(buffer,0,read);received+=read;
                    if(timer.ElapsedMilliseconds-lastMs>=500)
                    {
                        double speed=(received-last)/Math.Max(0.001,(timer.ElapsedMilliseconds-lastMs)/1000.0)/1024/1024;
                        int percent=total>0?(int)Math.Min(100,received*100/total):0;
                        status(String.Format("다운로드: {0} {1}% ({2:0.0}/{3:0.0} GB, {4:0.0} MB/s)",name,percent,received/1073741824.0,total/1073741824.0,speed));
                        last=received;lastMs=timer.ElapsedMilliseconds;
                    }
                }
            }
        }
        status("다운로드 수신 완료: "+name);
    }
    private static void DownloadParallel(string url,string path,string name,long expected,Action<string> status)
    {
        const int segmentCount=4;
        string[] parts=new string[segmentCount];
        long[] received=new long[segmentCount];
        int lastReported=-1;
        var tasks=new Task[segmentCount];
        status("고속 병렬 다운로드 시작: "+name);
        for(int index=0;index<segmentCount;index++)
        {
            int segment=index; long start=expected*segment/segmentCount; long end=expected*(segment+1)/segmentCount-1;
            parts[segment]=path+".segment"+segment;
            tasks[segment]=Task.Run(()=>{
                var request=(HttpWebRequest)WebRequest.Create(url);request.UserAgent="LAKIS-Installer/7.4.5";request.AllowAutoRedirect=true;request.Timeout=30000;request.ReadWriteTimeout=30000;request.AddRange(start,end);
                using(var response=(HttpWebResponse)request.GetResponse())
                {
                    ValidateDownloadOrigin(url,response.ResponseUri.AbsoluteUri);
                    if(response.StatusCode!=HttpStatusCode.PartialContent)throw new IOException("서버가 구간 다운로드를 지원하지 않습니다.");
                    ValidateContentRange(response.Headers["Content-Range"],start,end,expected,response.ContentLength);
                    using(Stream input=response.GetResponseStream())using(var output=new FileStream(parts[segment],FileMode.Create,FileAccess.Write,FileShare.Read))
                    {byte[] buffer=new byte[1024*1024];int read;while((read=input.Read(buffer,0,buffer.Length))>0){output.Write(buffer,0,read);int percent=-1;lock(received){received[segment]+=read;long total=0;for(int i=0;i<segmentCount;i++)total+=received[i];int current=(int)Math.Min(100,total*100/expected);if(current!=lastReported){lastReported=current;percent=current;}}if(percent>=0)status("고속 다운로드: "+name+" "+percent+"%");}}
                }
                if(new FileInfo(parts[segment]).Length!=end-start+1)throw new IOException("다운로드 구간 크기가 일치하지 않습니다.");
            });
        }
        try
        {
            Task.WaitAll(tasks);
            using(var output=new FileStream(path+".part",FileMode.Create,FileAccess.Write,FileShare.Read))
                foreach(string part in parts)using(var input=File.OpenRead(part))input.CopyTo(output,1024*1024);
            if(new FileInfo(path+".part").Length!=expected)throw new IOException("결합된 파일 크기가 일치하지 않습니다.");
            status("다운로드 수신 완료: "+name);
        }
        finally { foreach(string part in parts)try{if(File.Exists(part))File.Delete(part);}catch{} }
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
    private static string Hash(string path){using(var s=File.OpenRead(path))using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(s)).Replace("-","");}
    private static IOException CacheVerificationError(string path,string name,Exception error)
    {
        int code=error==null ? 0 : error.HResult&0xFFFF;
        bool blocked=error is IOException && (error.HResult&unchecked((int)0xFFFF0000))==unchecked((int)0x80070000) && (code==225||code==226);
        string detail=name+" | "+(error==null ? "unknown" : error.GetType().Name+" 0x"+error.HResult.ToString("X8"))+" | "+path;
        return new IOException(blocked
            ? "CACHE_SECURITY_BLOCKED: Windows 보안 또는 보안 프로그램이 다운로드 파일을 차단하거나 제거했습니다. 보안 프로그램의 보호 기록에서 파일과 탐지 내용을 확인해 주세요. 파일 검증을 완료하지 못해 설치를 중단했습니다. "+detail
            : "CACHE_VERIFY_OPEN_FAILED: "+detail,error);
    }
    private static string HashWithRetry(string path,string name)
    {
        Exception last=null;
        for(int attempt=1;attempt<=5;attempt++)try{return Hash(path);}catch(Exception error)
        {
            last=error;
            if(!IsTransientFileError(error))throw CacheVerificationError(path,name,error);
            if(attempt<5)System.Threading.Thread.Sleep(attempt*200);
        }
        throw CacheVerificationError(path,name,last);
    }
    private static string UniqueScratch(string cache,string prefix){return Path.Combine(cache,prefix+"-"+Guid.NewGuid().ToString("N"));}
    private static void ExtractZip(string archive,string destination)
    {
        RejectReparsePath(destination);
        string root=Path.GetFullPath(destination).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
        const string example="ComfyUI-RvTools_v2-d3f7e8beb477dff6c0fac44b298ab74ac433d93e/workflow/Workflow.png";
        using(var zip=ZipFile.OpenRead(FileSystemPath(archive)))
        {
          const int maxEntries=50000;
          const long maxExpanded=8L*1024*1024*1024,maxFile=2L*1024*1024*1024,maxRatio=10000;
          if(zip.Entries.Count>maxEntries)throw new IOException("ZIP_RESOURCE_LIMIT: too many entries");
          long expanded=0;
          bool remapExample=false;
          foreach(var entry in zip.Entries)if(entry.FullName==example)
          {
              remapExample=HashWithRetry(archive,"rvtools.zip")=="AC92C92CF6454E850E6A2B5053D13962BC2936539F669B910C4A49EDB875ECBD";
              break;
          }
          // Preserve the two case-colliding example images in this exact,
          // hash-verified upstream archive. Runtime file names stay unchanged.
          var seen=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
          var plan=new List<KeyValuePair<ZipArchiveEntry,string>>();
          foreach(var entry in zip.Entries)
          {
            if(entry.Length>maxFile||entry.Length>maxExpanded-expanded||entry.Length/Math.Max(1,entry.CompressedLength)>maxRatio)
                throw new IOException("ZIP_RESOURCE_LIMIT: expanded size or compression ratio");
            expanded+=entry.Length;
            if(((entry.ExternalAttributes>>16)&0xF000)==0xA000)throw new IOException("Unsafe ZIP link: "+entry.FullName);
            string member=remapExample&&entry.FullName==example ? example.Substring(0,example.Length-"Workflow.png".Length)+"Workflow-example.png" : entry.FullName;
            string relative=member.Replace('/',Path.DirectorySeparatorChar);
            // Modern IO preserves more Windows path syntax. ZIP members must
            // still be ordinary relative files, never ADS/device/rooted paths
            // or names whose trailing dots/spaces have ambiguous semantics.
            if(Path.IsPathRooted(relative)||relative.IndexOf(':')>=0)
                throw new IOException("Unsafe ZIP path: "+entry.FullName);
            foreach(string part in relative.Split(Path.DirectorySeparatorChar))
                if(part=="."||part==".."||part.EndsWith(".",StringComparison.Ordinal)||part.EndsWith(" ",StringComparison.Ordinal))
                    throw new IOException("Unsafe ZIP path: "+entry.FullName);
            string output=Path.GetFullPath(Path.Combine(destination,relative));
            if(!output.StartsWith(root,StringComparison.OrdinalIgnoreCase))throw new IOException("Unsafe ZIP path: "+entry.FullName);
            // Compare canonical Windows targets after the pinned remap, before
            // opening a file. Slash aliases and directory trailing slashes must
            // not let a later entry overwrite an earlier one.
            if(!seen.Add(output.TrimEnd(Path.DirectorySeparatorChar)))
                throw new IOException("Duplicate Windows ZIP path: "+entry.FullName);
            RejectReparsePath(output);
            plan.Add(new KeyValuePair<ZipArchiveEntry,string>(entry,output));
          }
          var files=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
          foreach(var copy in plan)if(!String.IsNullOrEmpty(copy.Key.Name))files.Add(copy.Value);
          foreach(var copy in plan)
            for(string parent=Path.GetDirectoryName(copy.Value);!String.IsNullOrEmpty(parent);parent=Path.GetDirectoryName(parent))
                if(files.Contains(parent))throw new IOException("Unsafe ZIP file/directory collision");
          // Reject the complete archive before creating any extracted file.
          foreach(var copy in plan)
          {
            var entry=copy.Key;
            RejectReparsePath(copy.Value);
            string output=FileSystemPath(copy.Value);
            if(String.IsNullOrEmpty(entry.Name)){Directory.CreateDirectory(output);continue;}
            Directory.CreateDirectory(Path.GetDirectoryName(output));
            using(Stream input=entry.Open())using(Stream file=new FileStream(output,FileMode.Create,FileAccess.Write,FileShare.None))input.CopyTo(file);
          }
        }
    }
    private static void RejectReparsePath(string path)
    {
        for(string current=Path.GetFullPath(path);!String.IsNullOrEmpty(current);current=Path.GetDirectoryName(current))
        {
            string full=FileSystemPath(current);
            try { if((File.GetAttributes(full)&FileAttributes.ReparsePoint)!=0)throw new IOException("Unsafe reparse destination: "+current); }
            catch(FileNotFoundException) { }
            catch(DirectoryNotFoundException) { }
        }
    }
    private static void Extract7z(string archive,string destination){string tool=Path.Combine(InstallerCache(),"7zr.exe");ExtractResource("LAKIS.7zr",tool);RunInstallerTool(tool,"x -y -o\""+FileSystemPath(destination)+"\" \""+FileSystemPath(archive)+"\"",destination,_=>{});if(!Directory.Exists(FileSystemPath(Path.Combine(destination,"ComfyUI_windows_portable"))))throw new IOException("ComfyUI 압축 해제 결과를 확인할 수 없습니다.");}
    internal static bool IsExistingInstallation(string target)
    {
        if(String.IsNullOrWhiteSpace(target))return false;
        try
        {
            string full=Path.GetFullPath(target);
            bool identity=File.Exists(Path.Combine(full,"VERSION"))&&File.Exists(Path.Combine(full,"ComfyUI","LAKIS","STOP_AUTOMATION"));
            bool runtime=Directory.Exists(Path.Combine(full,"ComfyUI"))&&(Directory.Exists(Path.Combine(full,"python_embeded"))||identity);
            bool marker=File.Exists(Path.Combine(full,"install.complete"))||File.Exists(Path.Combine(full,"VERSION"))||File.Exists(Path.Combine(full,"LAKIS.exe"));
            return runtime&&marker;
        }
        catch{return false;}
    }
    internal static bool HasDirectoryEntries(string target)
    {
        if(String.IsNullOrWhiteSpace(target))return false;
        try
        {
            if(!Directory.Exists(target))return false;
            using(var entries=Directory.EnumerateFileSystemEntries(target).GetEnumerator())return entries.MoveNext();
        }
        catch{return true;}
    }
    private static string PrepareTarget(string target,Action<string> status)
    {
        ValidateFreshTarget(target);
        Directory.CreateDirectory(target);status("빈 설치 폴더 확인 완료");return null;
    }
    private static void DeleteTree(string path){path=FileSystemPath(path);Exception last=null;for(int attempt=0;attempt<5;attempt++){try{if(!Directory.Exists(path))return;foreach(string file in Directory.GetFiles(path,"*",SearchOption.AllDirectories))try{File.SetAttributes(file,FileAttributes.Normal);}catch{}foreach(string dir in Directory.GetDirectories(path,"*",SearchOption.AllDirectories))try{File.SetAttributes(dir,FileAttributes.Normal);}catch{}File.SetAttributes(path,FileAttributes.Normal);Directory.Delete(path,true);return;}catch(Exception error){last=error;GC.Collect();GC.WaitForPendingFinalizers();System.Threading.Thread.Sleep(1000);}}throw last;}
    private static void Reset(string path){path=FileSystemPath(path);if(Directory.Exists(path))Directory.Delete(path,true);Directory.CreateDirectory(path);}
    private static void CopyTree(string source,string target)
    {
        source=FileSystemPath(source);target=FileSystemPath(target);
        RejectReparsePath(source);RejectReparsePath(target);
        string[] directories=Directory.GetDirectories(source,"*",SearchOption.AllDirectories);
        foreach(string dir in directories){RejectReparsePath(dir);RejectReparsePath(target+dir.Substring(source.Length));}
        string[] files=Directory.GetFiles(source,"*",SearchOption.AllDirectories);
        foreach(string file in files){RejectReparsePath(file);RejectReparsePath(target+file.Substring(source.Length));}
        Directory.CreateDirectory(target);
        foreach(string dir in directories)Directory.CreateDirectory(target+dir.Substring(source.Length));
        foreach(string file in files){string output=target+file.Substring(source.Length);Directory.CreateDirectory(Path.GetDirectoryName(output));CopyFile(file,output,true);}
    }
    private static void CopyFile(string source,string target,bool overwrite)
    {
        RejectReparsePath(source);RejectReparsePath(target);File.Copy(source,target,overwrite);
    }
    private static string FileSystemPath(string path)
    {
        string full=Path.GetFullPath(path);
        if(full.StartsWith(@"\\?\",StringComparison.Ordinal))return full;
        return full.StartsWith(@"\\",StringComparison.Ordinal)?@"\\?\UNC\"+full.Substring(2):@"\\?\"+full;
    }
    private static string InstallerCache()
    {
        // GetTempPath on older Windows/.NET can lose paths beyond MAX_PATH.
        // Preserve the documented TMP -> TEMP order without changing either value.
        string temporary=Environment.GetEnvironmentVariable("TMP");
        if(String.IsNullOrWhiteSpace(temporary))temporary=Environment.GetEnvironmentVariable("TEMP");
        if(String.IsNullOrWhiteSpace(temporary))temporary=Path.GetTempPath();
        string path=FileSystemPath(Path.Combine(temporary,"LAKIS-safe-v7.1"));
        Directory.CreateDirectory(path);
        return path;
    }
    private static void RunInstallerTool(string file,string args,string cwd,Action<string> status)
    {
        // CreateProcess still limits the executable path. Only self-contained,
        // verified installer tools use this private, temporary launch location.
        if(file.Length<260){Run(file,args,cwd,status);return;}
        string local=Environment.GetEnvironmentVariable("LOCALAPPDATA");
        if(String.IsNullOrWhiteSpace(local))local=Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string directory=Path.GetFullPath(Path.Combine(local,"LAKIS Studio","setup-tools",Guid.NewGuid().ToString("N")));
        string executable=Path.Combine(directory,Path.GetFileName(file));
        if(executable.Length>=260)throw new IOException("설치 도구 실행 경로가 너무 깁니다.");
        Directory.CreateDirectory(directory);
        try{CopyFile(file,executable,false);Run(executable,args,directory,status);}
        finally{DeleteTree(directory);}
    }
    private static void Run(string file,string args,string cwd,Action<string> status){var info=new ProcessStartInfo(file,args){WorkingDirectory=cwd,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true};using(var p=new Process{StartInfo=info}){p.OutputDataReceived+=(_,e)=>{if(!String.IsNullOrWhiteSpace(e.Data))status(e.Data);};p.ErrorDataReceived+=(_,e)=>{if(!String.IsNullOrWhiteSpace(e.Data))status(e.Data);};p.Start();p.BeginOutputReadLine();p.BeginErrorReadLine();p.WaitForExit();if(p.ExitCode!=0)throw new InvalidOperationException(Path.GetFileName(file)+" 종료 코드 "+p.ExitCode);}}
    private static void ExtractResource(string name,string path)
    {
        RejectReparsePath(path);
        byte[] payload;
        using(Stream input=Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
        {
            if(input==null)throw new IOException("내장 파일 누락: "+name);
            using(var memory=new MemoryStream()){input.CopyTo(memory);payload=memory.ToArray();}
        }
        if(File.Exists(path))
        {
            try
            {
                if(new FileInfo(path).Length==payload.LongLength)
                {
                    using(var sha=SHA256.Create())
                    {
                        string embedded=BitConverter.ToString(sha.ComputeHash(payload)).Replace("-","");
                        if(String.Equals(Hash(path),embedded,StringComparison.OrdinalIgnoreCase))return;
                    }
                }
            }
            catch(IOException){}
            catch(UnauthorizedAccessException){}
        }
        Exception last=null;
        for(int attempt=0;attempt<60;attempt++)
        {
            try
            {
                using(var output=new FileStream(path,FileMode.Create,FileAccess.Write,FileShare.None))output.Write(payload,0,payload.Length);
                return;
            }
            catch(IOException error){last=error;System.Threading.Thread.Sleep(500);}
            catch(UnauthorizedAccessException error){last=error;System.Threading.Thread.Sleep(500);}
        }
        throw new IOException("실행 파일 잠금이 해제되지 않았습니다: "+path,last);
    }
    private static void CreateDesktopShortcut(string target,Action<string> status)
    {
        string launcher=Path.Combine(target,"LAKIS_Desktop.exe");
        string icon=Path.Combine(target,"LAKIS.ico");
        string desktop=Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        string shortcutPath=Path.Combine(desktop,"LAKIS.lnk");
        Type shellType=Type.GetTypeFromProgID("WScript.Shell");
        if(shellType==null)throw new InvalidOperationException("Windows 바로가기 기능을 사용할 수 없습니다.");
        object shell=Activator.CreateInstance(shellType);
        object shortcut=shellType.InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[]{shortcutPath});
        Type shortcutType=shortcut.GetType();
        shortcutType.InvokeMember("TargetPath",BindingFlags.SetProperty,null,shortcut,new object[]{launcher});
        shortcutType.InvokeMember("WorkingDirectory",BindingFlags.SetProperty,null,shortcut,new object[]{target});
        shortcutType.InvokeMember("IconLocation",BindingFlags.SetProperty,null,shortcut,new object[]{(File.Exists(icon)?icon:launcher)+",0"});
        shortcutType.InvokeMember("Description",BindingFlags.SetProperty,null,shortcut,new object[]{"LAKIS Studio 실행"});
        shortcutType.InvokeMember("Save",BindingFlags.InvokeMethod,null,shortcut,null);
        status("바탕화면 바로가기 생성: LAKIS");
    }
    private static void StopOwned(string target)
    {
        string prefix=Path.GetFullPath(target).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
        var remaining = new List<int>();
        int ownPid = Process.GetCurrentProcess().Id;
        for(int attempt=0;attempt<6;attempt++)
        {
            remaining.Clear();
            foreach(Process p in Process.GetProcesses())
            {
                try
                {
                    if (p.Id != ownPid && !p.HasExited &&
                        p.MainModule.FileName.StartsWith(prefix,StringComparison.OrdinalIgnoreCase))
                        remaining.Add(p.Id);
                }
                catch (System.ComponentModel.Win32Exception) { }
                catch (InvalidOperationException) { }
                finally { p.Dispose(); }
            }
            if(remaining.Count == 0)return;
            System.Threading.Thread.Sleep(500);
        }
        throw new IOException("설치 폴더를 사용하는 프로그램이 실행 중입니다. LAKIS와 해당 ComfyUI를 종료한 뒤 다시 시도하세요. PID: " + String.Join(",", remaining));
    }
}
