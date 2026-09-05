using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

internal sealed class DownloadItem
{
    internal string Name, Url, Sha, Destination;
    internal long Bytes;
    internal DownloadItem(string name, string url, string sha, string destination = null, long bytes = 0)
    { Name = name; Url = url; Sha = sha; Destination = destination; Bytes = bytes; }
}

internal sealed class SafeSetupForm : Form
{
    private readonly TextBox destination = new TextBox();
    private readonly Label status = new Label();
    private readonly ProgressBar progress = new ProgressBar();
    private readonly Button install = new Button();
    private readonly Button repair = new Button();
    private readonly CheckBox launch = new CheckBox();

    internal SafeSetupForm()
    {
        Text = "LAKIS 설치"; Width = 590; Height = 310; FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false; StartPosition = FormStartPosition.CenterScreen;
        Controls.Add(new Label { Left=24,Top=20,Width=530,Height=36,Text="LAKIS Studio",Font=new Font("Segoe UI",17,FontStyle.Bold) });
        Controls.Add(new Label { Left=26,Top=62,Width=530,Height=38,Text="공식 배포처에서 검증된 구성요소를 다운로드합니다.\n최소 15GB의 여유 공간이 필요합니다." });
        Controls.Add(new Label { Left=26,Top=112,Width=100,Text="설치 위치" });
        destination.SetBounds(26,134,530,25);
        destination.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","LAKIS");
        progress.SetBounds(26,172,530,18); progress.Minimum=0; progress.Maximum=100;
        status.SetBounds(26,198,530,34); status.Text="설치 준비 완료";
        launch.SetBounds(26,238,260,25); launch.Text="설치 후 LAKIS 실행"; launch.Checked=true;
        repair.SetBounds(330,234,110,32); repair.Text="기존 설치 복구"; repair.Click += async (_,__) => await RepairAsync();
        install.SetBounds(446,234,110,32); install.Text="새로 설치"; install.Click += async (_,__) => await InstallAsync();
        Controls.AddRange(new Control[]{destination,progress,status,launch,repair,install});
    }

    private async Task InstallAsync()
    {
        string target;
        try { target = Path.GetFullPath(destination.Text.Trim()); }
        catch { MessageBox.Show("설치 위치가 올바르지 않습니다."); return; }
        if (target.Length < 8) { MessageBox.Show("설치 위치가 너무 넓습니다."); return; }
        var drive = new DriveInfo(Path.GetPathRoot(target));
        if (drive.AvailableFreeSpace < 15L*1024*1024*1024) { MessageBox.Show("최소 15GB의 여유 공간이 필요합니다."); return; }
        install.Enabled=false; repair.Enabled=false; destination.Enabled=false;
        try
        {
            await Task.Run(() => SafeInstaller.Install(target, line => BeginInvoke((Action)(() => {
                status.Text=line; if(line.IndexOf('%')<0&&progress.Value<95) progress.Value++;
            }))));
            progress.Value=100; status.Text="설치 완료";
            MessageBox.Show("LAKIS 설치가 완료되었습니다.","LAKIS",MessageBoxButtons.OK,MessageBoxIcon.Information);
            if(launch.Checked) Process.Start(Path.Combine(target,"LAKIS.exe"));
            Close();
        }
        catch(Exception error)
        {
            install.Enabled=true; repair.Enabled=true; destination.Enabled=true; status.Text="설치 실패";
            MessageBox.Show(error.Message,"LAKIS 설치 오류",MessageBoxButtons.OK,MessageBoxIcon.Error);
        }
    }

    private async Task RepairAsync()
    {
        string target;try{target=Path.GetFullPath(destination.Text.Trim());}catch{MessageBox.Show("설치 위치가 올바르지 않습니다.");return;}
        install.Enabled=false;repair.Enabled=false;destination.Enabled=false;
        try{await Task.Run(()=>SafeInstaller.Repair(target,line=>BeginInvoke((Action)(()=>{status.Text=line;if(progress.Value<95)progress.Value++;}))));progress.Value=100;status.Text="복구 완료";MessageBox.Show("기존 LAKIS 설치 복구가 완료되었습니다.","LAKIS",MessageBoxButtons.OK,MessageBoxIcon.Information);if(launch.Checked)Process.Start(Path.Combine(target,"LAKIS.exe"));Close();}
        catch(Exception error){install.Enabled=true;repair.Enabled=true;destination.Enabled=true;status.Text="복구 실패";MessageBox.Show(error.Message,"LAKIS 복구 오류",MessageBoxButtons.OK,MessageBoxIcon.Error);}
    }

    [STAThread] private static int Main(string[] args)
    {
        string target = null;
        for(int i=0;i+1<args.Length;i++) if(args[i]=="--install-dir") target=args[i+1];
        if(Array.Exists(args,a=>a=="--headless"))
        {
            try { if(String.IsNullOrWhiteSpace(target)) return 2;if(Array.Exists(args,a=>a=="--repair"))SafeInstaller.Repair(Path.GetFullPath(target),Console.WriteLine);else SafeInstaller.Install(Path.GetFullPath(target),Console.WriteLine); return 0; }
            catch(Exception error) { Console.Error.WriteLine(error); return 1; }
        }
        Application.EnableVisualStyles(); Application.Run(new SafeSetupForm()); return 0;
    }
}

internal static class SafeInstaller
{
    private const string Revision = "v7.1.2";
    private static readonly DownloadItem Portable = new DownloadItem("ComfyUI v0.21.1",
        "https://github.com/Comfy-Org/ComfyUI/releases/download/v0.21.1/ComfyUI_windows_portable_nvidia.7z",
        "7C380D4309BBDA395366C49564EDF8996181FD45E61B6F353EA417F32BC3B970",null,2001582790);
    private static readonly DownloadItem LoraManager = new DownloadItem("lora-manager","https://codeload.github.com/willmiao/ComfyUI-Lora-Manager/zip/df34efafbc604fa81fbd58f09f723842a73dadfd","CC037E1AD77AAA092F81928BCEE1E0313687EA0B8A6BE7827D131C0C0D15C605","ComfyUI-Lora-Manager",17027774);
    private static readonly DownloadItem[] Nodes = new[]{
        new DownloadItem("ultimate","https://codeload.github.com/ssitu/ComfyUI_UltimateSDUpscale/zip/a5547db9e1d07d3318bb21e9e9c474f4c1e9c8df","47EF9D567D20A2EF8B96FF9A3E1BBED8F764FFB04988D0D4B32D020281FC73D1","comfyui_ultimatesdupscale"),
        new DownloadItem("anima-dave","https://codeload.github.com/sorryhyun/ComfyUI-Anima-DAVE/zip/83143e8d84768e25f72755ec00ea00ded07ee06e","730728376A7C6F8948E87D1ABCC021B55D5DEEACA251EFC5C9EB748BF386717E","comfyui-anima-dave"),
        new DownloadItem("custom-scripts","https://codeload.github.com/pythongosssss/ComfyUI-Custom-Scripts/zip/609f3afaa74b2f88ef9ce8d939626065e3247469","C82B520F2A1EB769742EA1C385D2C3522257A8B6A732F7DEF128871352334337","comfyui-custom-scripts"),
        new DownloadItem("dcw","https://codeload.github.com/namemechan/ComfyUI-DCW/zip/66aaf9dddb03bad031c1e8443e255a811008e477","E8364A6D88540CF22D771203A336BAB98C78FE4FB9E49607624EEC316CBE22DA","ComfyUI-DCW"),
        new DownloadItem("easy-use","https://codeload.github.com/yolain/ComfyUI-Easy-Use/zip/b5e31ef12ad9d0b187b545c2707735cc7d581c52","7894B746CF576BE4FF9A4DAD056D0D214E8946344BC359273AC3339500BE7BD3","comfyui-easy-use"),
        new DownloadItem("easyuse-anima","https://codeload.github.com/n0va39/ComfyUI-EasyUseAnima/zip/c64236a5b64db3c1b5db4e333931ab7128a70200","9F4B6970FDC88768F83AD40974B38B7056DE8E07735532446587D97C808FDCDB","comfyui-easyuse-anima"),
        new DownloadItem("image-saver","https://codeload.github.com/alexopus/ComfyUI-Image-Saver/zip/2ba0f2bc4ee5235a0f9299f415fb2fb6be78f9e9","72C8D32675802D3014B88792CFEA44E3082949AA1AF2981A8615CF81801B6EE2","comfyui-image-saver"),
        LoraManager,
        new DownloadItem("impact-pack","https://codeload.github.com/ltdrdata/ComfyUI-Impact-Pack/zip/429d0159ad429e64d2b3916e6e7be9c22d025c3c","017BD1DDB7D17C923A1309FF1251379EAF65B71A9AC8FA91D384BB275BF000CE","comfyui-impact-pack"),
        new DownloadItem("kjnodes","https://codeload.github.com/kijai/ComfyUI-KJNodes/zip/e8e88f7c88e3f6205b122f5de87e69a09fbce5ac","A07EE4454557012F4640FDF0C0C96EAD1B960D2A07D02F10037F63B7E2A0339E","comfyui-kjnodes"),
        new DownloadItem("rvtools","https://codeload.github.com/r-vage/ComfyUI-RvTools_v2/zip/d3f7e8beb477dff6c0fac44b298ab74ac433d93e","AC92C92CF6454E850E6A2B5053D13962BC2936539F669B910C4A49EDB875ECBD","comfyui-rvtools_v2"),
        new DownloadItem("spectrum","https://codeload.github.com/sorryhyun/ComfyUI-Spectrum-KSampler/zip/b46a364aec3b161b889c9cc26cd976a49eb537ae","3347FE5B9FA25C53E1FA45343BD04AE984A4BE32FCF83F3B520A473596EB3F88","comfyui-spectrum-ksampler"),
        new DownloadItem("rgthree","https://codeload.github.com/rgthree/rgthree-comfy/zip/13b4399c00b5ef5a97b1b6800fc1185874740f5d","99C509D618E9380C8D4ACC6990C7A62AE8B6765D2B6B26272BD711276E0FA8CE","rgthree-comfy"),
        new DownloadItem("was","https://codeload.github.com/ltdrdata/was-node-suite-comfyui/zip/44de705818d4663fefefde57ffe0ea5a9ea39df4","1512EE7897052BF55AA472425BFABBBE6462D01F91684EB4494D4A6C3EC79DE5","was-ns")};
    private static readonly DownloadItem Usdu = new DownloadItem("ultimate-upstream","https://codeload.github.com/Coyote-A/ultimate-upscale-for-automatic1111/zip/2322caa480535b1011a1f9c18126d85ea444f146","0797D41BAD17B4BD9C41FAE0FF4EA110CC364C1D2A06E13B27CA78FD0D4C57D7",null,19299);
    private static readonly DownloadItem[] Models = new[]{
        new DownloadItem("anima_baseV10.safetensors","https://huggingface.co/p101111/anima/resolve/3c8cbe9a9358103947d0bf8a59e8e4f1a12c077f/diffusion_models/anima_baseV10.safetensors","BD43B7CFFE1ED1153D9C41E7BEB2F18CB1273EAFBAA3AF3EDD6A173DC90A006E","diffusion_models",4182218328),
        new DownloadItem("qwen_3_06b_base.safetensors","https://huggingface.co/Aitrepreneur/FLX/resolve/93321be18059c4d735de86bf6162ea8493bf51e8/qwen_3_06b_base.safetensors","CD2A512003E2F9F3CD3C32A9C3573F820BB28C940F73C57B1DDAA983D9223EBA","text_encoders",1192135096),
        new DownloadItem("qwen_image_vae.safetensors","https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/7beb7b647f04469fbe64ba8adc2bb0d7e5e9f73f/split_files/vae/qwen_image_vae.safetensors","A70580F0213E67967EE9C95F05BB400E8FB08307E017A924BF3441223E023D1F","vae",253806246),
        new DownloadItem("anima-turbo-lora-v0.2.safetensors","https://huggingface.co/circlestone-labs/Anima-Official-LoRAs/resolve/218b5466a07e8a79328dd8b73ff810706d73cb86/anima-turbo-lora-v0.2.safetensors","1B55E40BDB1D0E5A78CB498F245FCCFDAAE97823265DB957D2AABDCF4CD3CAF1","loras",148902616),
        new DownloadItem("sam3.1_multiplex_fp16.safetensors","https://huggingface.co/Comfy-Org/sam3.1/resolve/f38cd62b71494b53ac2b56ca36e24f3c8d565581/checkpoints/sam3.1_multiplex_fp16.safetensors","9BA99C92703C2E8B4F47DE2D34A539BB8E18923049E238B780D70DBE6368EB03","checkpoints",1745546848),
        new DownloadItem("2x-AnimeSharpV4_Fast_RCAN_PU.safetensors","https://huggingface.co/Kim2091/2x-AnimeSharpV4/resolve/1a9339b5c308ab3990f6233be2c1169a75772878/2x-AnimeSharpV4_Fast_RCAN_PU.safetensors","B641C9EB10B43F26538177AA8F0FEF8B9FC2A153AFD1431D0A062A84C49CE6D0","upscale_models",31359158),
        new DownloadItem("pooled_text_proj-0611.safetensors","https://github.com/sorryhyun/ComfyUI-Spectrum-KSampler/releases/download/0605/pooled_text_proj-0611.safetensors","C8B33DD35F9DF2AAA54224278417A4BBC0DDE695F38A1DB1581E2E9E7E87C040","anima_mod_guidance",12591416)};

    internal static void Install(string target, Action<string> report)
    {
        ServicePointManager.SecurityProtocol=(SecurityProtocolType)3072;
        string cache=Path.Combine(Path.GetTempPath(),"LAKIS-safe-v7.1"); Directory.CreateDirectory(cache);
        var log=new List<string>(); Action<string> status=s=>{lock(log)log.Add(s);report(s);};
        string previous=null;
        try
        {
            StopOwned(target); previous=PrepareTarget(target,status);
            string portable=Fetch(Portable,cache,status); status("ComfyUI 압축 해제"); Extract7z(portable,target);
            string nested=Path.Combine(target,"ComfyUI_windows_portable"); foreach(string entry in Directory.GetFileSystemEntries(nested)) Move(entry,target); try{DeleteTree(nested);}catch{}
            string comfy=Path.Combine(target,"ComfyUI"), custom=Path.Combine(comfy,"custom_nodes");
            if(Directory.Exists(custom))try{DeleteTree(custom);}catch{status("잠긴 커스텀 노드 폴더를 덮어써 복구합니다");} Directory.CreateDirectory(custom);
            foreach(var node in Nodes) InstallZip(node,cache,Path.Combine(custom,node.Destination),status);
            InstallZip(Usdu,cache,Path.Combine(custom,"comfyui_ultimatesdupscale","repositories","ultimate_sd_upscale"),status);
            var lakisItem=new DownloadItem("LAKIS","https://codeload.github.com/Jeong-Luke/LAKIS/zip/"+Revision,"",null);
            string lakisZip=Path.Combine(cache,"LAKIS-"+Revision+".zip"); if(!File.Exists(lakisZip)){status("LAKIS UI 다운로드");Download(lakisItem.Url,lakisZip,"LAKIS UI",0,status);}
            string lakisStage=Path.Combine(cache,"LAKIS-"+Revision);Reset(lakisStage);ExtractZip(lakisZip,lakisStage);string lakis=FirstDirectory(lakisStage);
            foreach(string node in Directory.GetDirectories(Path.Combine(lakis,"src","custom_nodes"))) CopyTree(node,Path.Combine(custom,Path.GetFileName(node)));
            CopyTree(Path.Combine(lakis,"src","external_ui"),Path.Combine(comfy,"LAKIS_DEV","external_ui"));
            Directory.CreateDirectory(Path.Combine(comfy,"LAKIS_DEV"));File.WriteAllText(Path.Combine(comfy,"LAKIS_DEV","STOP_AUTOMATION"),"LAKIS owns this runtime.");
            Directory.CreateDirectory(Path.Combine(comfy,"LAKIS","workflows"));File.Copy(Path.Combine(lakis,"src","runtime","sync_runtime_workflow.py"),Path.Combine(comfy,"LAKIS","sync_runtime_workflow.py"),true);
            File.Copy(Path.Combine(lakis,"workflows","LAKIS_runtime_api_v7.1.json"),Path.Combine(comfy,"LAKIS","workflows","LAKIS_runtime_api_v7.1.json"),true);
            Directory.CreateDirectory(Path.Combine(comfy,"user","default","workflows"));File.Copy(Path.Combine(lakis,"workflows","LAKIS_custom_v7.1.json"),Path.Combine(comfy,"user","default","workflows","LAKIS_custom_v7.1.json"),true);
            File.Copy(Path.Combine(lakis,"patches","ComfyUI-Spectrum-KSampler","files","nodes.py"),Path.Combine(custom,"comfyui-spectrum-ksampler","nodes.py"),true);
            File.Copy(Path.Combine(lakis,"patches","ComfyUI-Spectrum-KSampler","files","spectrum.py"),Path.Combine(custom,"comfyui-spectrum-ksampler","spectrum.py"),true);
            Directory.CreateDirectory(Path.Combine(comfy,"input"));using(var bitmap=new Bitmap(1536,1024)){using(Graphics g=Graphics.FromImage(bitmap)){g.Clear(Color.FromArgb(26,29,42));g.FillEllipse(Brushes.SlateBlue,540,100,456,456);}bitmap.Save(Path.Combine(comfy,"input","LAKIS_1_2026-09-01-221228.webp"),ImageFormat.Png);}
            foreach(var model in Models){string cached=Fetch(model,cache,status);string folder=Path.Combine(comfy,"models",model.Destination);Directory.CreateDirectory(folder);File.Copy(cached,Path.Combine(folder,model.Name),true);}
            string python=Path.Combine(target,"python_embeded","python.exe");foreach(string node in Directory.GetDirectories(custom)){string req=Path.Combine(node,"requirements.txt");if(File.Exists(req)){status("의존성 설치: "+Path.GetFileName(node));string safeReq=PrepareRequirements(req);Run(python,"-s -m pip install --disable-pip-version-check -r \""+safeReq+"\"",target,status);}}
            ExtractDesktopRuntime(target,status);
            CreateDesktopShortcut(target,status);
            File.WriteAllText(Path.Combine(target,"VERSION"),"7.1.2");File.WriteAllText(Path.Combine(target,"install.complete"),DateTime.UtcNow.ToString("O"));File.WriteAllLines(Path.Combine(target,"network-install.log"),log.ToArray());if(previous!=null)try{DeleteTree(previous);}catch{status("이전 설치 폴더는 재부팅 후 삭제할 수 있습니다: "+previous);}status("설치 완료");
        }
        catch(Exception error){try{Directory.CreateDirectory(target);File.WriteAllLines(Path.Combine(target,"network-install.log"),log.ToArray());}catch{}throw new InvalidOperationException("설치 중 오류가 발생했습니다.\n"+error.Message+"\n\n로그: "+Path.Combine(target,"network-install.log"),error);}
    }
    internal static void Repair(string target,Action<string> report)
    {
        ServicePointManager.SecurityProtocol=(SecurityProtocolType)3072;
        string comfy=Path.Combine(target,"ComfyUI"),python=Path.Combine(target,"python_embeded","python.exe");
        if(!Directory.Exists(comfy)||!File.Exists(python))throw new InvalidOperationException("완료된 LAKIS 설치를 찾을 수 없습니다. 설치 위치를 확인하거나 새로 설치를 선택하세요.");
        var log=new List<string>();Action<string> status=s=>{log.Add(s);report(s);};
        try
        {
            StopOwned(target);
            string cache=Path.Combine(Path.GetTempPath(),"LAKIS-safe-v7.1");Directory.CreateDirectory(cache);
            string custom=Path.Combine(comfy,"custom_nodes");Directory.CreateDirectory(custom);
            status("LoRA Manager 다운로드 및 검증");InstallZip(LoraManager,cache,Path.Combine(custom,LoraManager.Destination),status);
            string req=Path.Combine(custom,LoraManager.Destination,"requirements.txt");status("LoRA Manager 의존성 복구");
            Run(python,"-s -m pip install --disable-pip-version-check -r \""+req+"\"",target,status);
            status("LAKIS 실행 구성 복구");
            var uiItem=new DownloadItem("LAKIS-repair","https://codeload.github.com/Jeong-Luke/LAKIS/zip/"+Revision,"",null);
            string uiZip=Path.Combine(cache,"LAKIS-repair-"+Revision+".zip");
            if(!File.Exists(uiZip))Download(uiItem.Url,uiZip,"LAKIS UI",0,status);
            string uiStage=Path.Combine(cache,"LAKIS-repair-"+Revision);Reset(uiStage);ExtractZip(uiZip,uiStage);
            string uiRoot=FirstDirectory(uiStage);CopyTree(Path.Combine(uiRoot,"src","external_ui"),Path.Combine(comfy,"LAKIS_DEV","external_ui"));
            ExtractDesktopRuntime(target,status);
            CreateDesktopShortcut(target,status);
            File.WriteAllText(Path.Combine(target,"VERSION"),"7.1.2");File.WriteAllLines(Path.Combine(target,"repair.log"),log.ToArray());status("복구 완료");
        }
        catch(Exception error){try{File.WriteAllLines(Path.Combine(target,"repair.log"),log.ToArray());}catch{}throw new InvalidOperationException("복구 중 오류가 발생했습니다.\n"+error.Message+"\n\n로그: "+Path.Combine(target,"repair.log"),error);}
    }
    private static string Fetch(DownloadItem item,string cache,Action<string> status){string path=Path.Combine(cache,item.Name.Replace('/','_'));if(File.Exists(path)&&(item.Bytes>0&&new FileInfo(path).Length!=item.Bytes||item.Sha.Length>0&&!String.Equals(Hash(path),item.Sha,StringComparison.OrdinalIgnoreCase)))File.Delete(path);if(!File.Exists(path))Download(item.Url,path,item.Name,item.Bytes,status);if(item.Bytes>0&&new FileInfo(path).Length!=item.Bytes)throw new IOException("크기 검증 실패: "+item.Name);if(item.Sha.Length>0&&!String.Equals(Hash(path),item.Sha,StringComparison.OrdinalIgnoreCase))throw new IOException("SHA-256 검증 실패: "+item.Name);return path;}
    private static void Download(string url,string path,string name,long expected,Action<string> status){string part=path+".part";long offset=File.Exists(part)?new FileInfo(part).Length:0;if(expected>0&&offset>expected){File.Delete(part);offset=0;}var request=(HttpWebRequest)WebRequest.Create(url);request.UserAgent="LAKIS-Installer/7.1.2";request.AllowAutoRedirect=true;if(offset>0)request.AddRange(offset);using(var response=(HttpWebResponse)request.GetResponse()){bool resumed=response.StatusCode==HttpStatusCode.PartialContent;if(offset>0&&!resumed)offset=0;long total=expected>0?expected:offset+response.ContentLength;using(Stream input=response.GetResponseStream())using(var output=new FileStream(part,resumed?FileMode.Append:FileMode.Create,FileAccess.Write,FileShare.Read)){byte[] buffer=new byte[1024*1024];long received=offset,last=offset;var timer=Stopwatch.StartNew();long lastMs=0;int read;while((read=input.Read(buffer,0,buffer.Length))>0){output.Write(buffer,0,read);received+=read;if(timer.ElapsedMilliseconds-lastMs>=500){double speed=(received-last)/Math.Max(0.001,(timer.ElapsedMilliseconds-lastMs)/1000.0)/1024/1024;int percent=total>0?(int)Math.Min(100,received*100/total):0;status(String.Format("다운로드: {0} {1}% ({2:0.0}/{3:0.0} GB, {4:0.0} MB/s)",name,percent,received/1073741824.0,total/1073741824.0,speed));last=received;lastMs=timer.ElapsedMilliseconds;}}} }if(File.Exists(path))File.Delete(path);File.Move(part,path);status("다운로드 완료: "+name);}
    private static string Hash(string path){using(var s=File.OpenRead(path))using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(s)).Replace("-","");}
    private static void InstallZip(DownloadItem item,string cache,string destination,Action<string> status){string zip=Fetch(item,cache,status),stage=Path.Combine(cache,"unpack-"+item.Name);Reset(stage);ExtractZip(zip,stage);string source=FirstDirectory(stage);if(Directory.Exists(destination))try{DeleteTree(destination);}catch{}Directory.CreateDirectory(Path.GetDirectoryName(destination));if(Directory.Exists(destination)){CopyTree(source,destination);try{DeleteTree(source);}catch{}}else Directory.Move(source,destination);}
    private static void ExtractZip(string archive,string destination){string root=Path.GetFullPath(destination).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;using(var zip=ZipFile.OpenRead(archive)){foreach(var entry in zip.Entries){string output=Path.GetFullPath(Path.Combine(destination,entry.FullName.Replace('/',Path.DirectorySeparatorChar)));if(!output.StartsWith(root,StringComparison.OrdinalIgnoreCase))throw new IOException("Unsafe ZIP path: "+entry.FullName);if(String.IsNullOrEmpty(entry.Name)){Directory.CreateDirectory(output);continue;}Directory.CreateDirectory(Path.GetDirectoryName(output));using(Stream input=entry.Open())using(Stream file=new FileStream(output,FileMode.Create,FileAccess.Write,FileShare.None))input.CopyTo(file);}}}
    private static void Extract7z(string archive,string destination){string tool=Path.Combine(Path.GetTempPath(),"LAKIS-safe-v7.1","7zr.exe");ExtractResource("LAKIS.7zr",tool);Run(tool,"x -y -o\""+destination+"\" \""+archive+"\"",destination,_=>{});if(!Directory.Exists(Path.Combine(destination,"ComfyUI_windows_portable")))throw new IOException("ComfyUI 압축 해제 결과를 확인할 수 없습니다.");}
    private static string PrepareRequirements(string source){string text=File.ReadAllText(source);text=text.Replace("git+https://github.com/facebookresearch/sam2","https://codeload.github.com/facebookresearch/sam2/zip/2b90b9f5ceec907a1c18123530e92e794ad901a4").Replace("git+https://github.com/ltdrdata/img2texture.git","https://codeload.github.com/ltdrdata/img2texture/zip/d6159abea44a0b2cf77454d3d46962c8b21eb9d3").Replace("git+https://github.com/ltdrdata/cstr","https://codeload.github.com/ltdrdata/cstr/zip/0520c29a18a7a869a6e5983861d6f7a4c86f8e9b").Replace("git+https://github.com/ltdrdata/ffmpy.git","https://codeload.github.com/ltdrdata/ffmpy/zip/f000737698b387ffaeab7cd871b0e9185811230d");string output=source+".lakis.txt";File.WriteAllText(output,text);return output;}
    private static string PrepareTarget(string target,Action<string> status){if(!Directory.Exists(target)){Directory.CreateDirectory(target);return null;}try{DeleteTree(target);Directory.CreateDirectory(target);}catch(Exception){status("잠긴 이전 설치 파일을 덮어써 복구합니다");Directory.CreateDirectory(target);}return null;}
    private static void DeleteTree(string path){Exception last=null;for(int attempt=0;attempt<5;attempt++){try{if(!Directory.Exists(path))return;foreach(string file in Directory.GetFiles(path,"*",SearchOption.AllDirectories))try{File.SetAttributes(file,FileAttributes.Normal);}catch{}foreach(string dir in Directory.GetDirectories(path,"*",SearchOption.AllDirectories))try{File.SetAttributes(dir,FileAttributes.Normal);}catch{}File.SetAttributes(path,FileAttributes.Normal);Directory.Delete(path,true);return;}catch(Exception error){last=error;GC.Collect();GC.WaitForPendingFinalizers();System.Threading.Thread.Sleep(1000);}}throw last;}
    private static void Reset(string path){if(Directory.Exists(path))Directory.Delete(path,true);Directory.CreateDirectory(path);}
    private static string FirstDirectory(string path){string[] dirs=Directory.GetDirectories(path);if(dirs.Length==0)throw new IOException("빈 압축 파일: "+path);return dirs[0];}
    private static void Move(string entry,string target){string output=Path.Combine(target,Path.GetFileName(entry));if(Directory.Exists(entry)){if(Directory.Exists(output)){CopyTree(entry,output);try{DeleteTree(entry);}catch{}}else Directory.Move(entry,output);}else{if(File.Exists(output))File.Delete(output);File.Move(entry,output);}}
    private static void CopyTree(string source,string target){Directory.CreateDirectory(target);foreach(string dir in Directory.GetDirectories(source,"*",SearchOption.AllDirectories))Directory.CreateDirectory(dir.Replace(source,target));foreach(string file in Directory.GetFiles(source,"*",SearchOption.AllDirectories)){string output=file.Replace(source,target);Directory.CreateDirectory(Path.GetDirectoryName(output));File.Copy(file,output,true);}}
    private static void Run(string file,string args,string cwd,Action<string> status){var info=new ProcessStartInfo(file,args){WorkingDirectory=cwd,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true};using(var p=new Process{StartInfo=info}){p.OutputDataReceived+=(_,e)=>{if(!String.IsNullOrWhiteSpace(e.Data))status(e.Data);};p.ErrorDataReceived+=(_,e)=>{if(!String.IsNullOrWhiteSpace(e.Data))status(e.Data);};p.Start();p.BeginOutputReadLine();p.BeginErrorReadLine();p.WaitForExit();if(p.ExitCode!=0)throw new InvalidOperationException(Path.GetFileName(file)+" 종료 코드 "+p.ExitCode);}}
    private static void ExtractResource(string name,string path){using(Stream input=Assembly.GetExecutingAssembly().GetManifestResourceStream(name)){if(input==null)throw new IOException("내장 파일 누락: "+name);using(var output=File.Create(path))input.CopyTo(output);}}
    private static void ExtractDesktopRuntime(string target,Action<string> status)
    {
        status("LAKIS 독립 실행 창 설치");
        ExtractResource("LAKIS.Launcher",Path.Combine(target,"LAKIS.exe"));
        ExtractResource("LAKIS.Updater",Path.Combine(target,"LAKIS_Updater.exe"));
        ExtractResource("LAKIS.Updater",Path.Combine(target,"LAKIS_Patcher.exe"));
        ExtractResource("LAKIS.Desktop",Path.Combine(target,"LAKIS_Desktop.exe"));
        ExtractResource("LAKIS.WebView2.Core",Path.Combine(target,"Microsoft.Web.WebView2.Core.dll"));
        ExtractResource("LAKIS.WebView2.WinForms",Path.Combine(target,"Microsoft.Web.WebView2.WinForms.dll"));
        ExtractResource("LAKIS.WebView2.Loader",Path.Combine(target,"WebView2Loader.dll"));
        ExtractResource("LAKIS.Uninstaller",Path.Combine(target,"Uninstall_LAKIS.exe"));
        EnsureWebView2Runtime(status);
    }
    private static bool HasWebView2Runtime()
    {
        string[] paths={@"SOFTWARE\Microsoft\EdgeUpdate\Clients",@"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"};
        RegistryKey[] roots={Registry.LocalMachine,Registry.CurrentUser};
        foreach(RegistryKey root in roots)foreach(string path in paths)try
        {
            using(RegistryKey clients=root.OpenSubKey(path))
            {
                if(clients==null)continue;
                foreach(string keyName in clients.GetSubKeyNames())using(RegistryKey product=clients.OpenSubKey(keyName))
                {
                    string name=Convert.ToString(product.GetValue("name"));
                    string version=Convert.ToString(product.GetValue("pv"));
                    if(name.IndexOf("WebView2",StringComparison.OrdinalIgnoreCase)>=0&&!String.IsNullOrWhiteSpace(version)&&version!="0.0.0.0")return true;
                }
            }
        }catch{}
        return false;
    }
    private static void EnsureWebView2Runtime(Action<string> status)
    {
        if(HasWebView2Runtime()){status("Microsoft WebView2 Runtime 확인 완료");return;}
        string setup=Path.Combine(Path.GetTempPath(),"LAKIS-safe-v7.1","MicrosoftEdgeWebview2Setup.exe");
        Directory.CreateDirectory(Path.GetDirectoryName(setup));
        status("Microsoft WebView2 Runtime 다운로드");
        Download("https://go.microsoft.com/fwlink/p/?LinkId=2124703",setup,"Microsoft WebView2 Runtime",0,status);
        X509Certificate2 certificate=new X509Certificate2(X509Certificate.CreateFromSignedFile(setup));
        if(certificate.Subject.IndexOf("Microsoft Corporation",StringComparison.OrdinalIgnoreCase)<0)throw new InvalidDataException("WebView2 설치 파일의 Microsoft 서명을 확인할 수 없습니다.");
        status("Microsoft WebView2 Runtime 설치");
        Run(setup,"/silent /install",Path.GetDirectoryName(setup),status);
        if(!HasWebView2Runtime())throw new InvalidOperationException("WebView2 Runtime 설치를 확인할 수 없습니다. Windows를 다시 시작한 뒤 복구를 실행해 주세요.");
    }
    private static void CreateDesktopShortcut(string target,Action<string> status)
    {
        string launcher=Path.Combine(target,"LAKIS.exe");
        string desktop=Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        string shortcutPath=Path.Combine(desktop,"LAKIS.lnk");
        Type shellType=Type.GetTypeFromProgID("WScript.Shell");
        if(shellType==null)throw new InvalidOperationException("Windows 바로가기 기능을 사용할 수 없습니다.");
        object shell=Activator.CreateInstance(shellType);
        object shortcut=shellType.InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[]{shortcutPath});
        Type shortcutType=shortcut.GetType();
        shortcutType.InvokeMember("TargetPath",BindingFlags.SetProperty,null,shortcut,new object[]{launcher});
        shortcutType.InvokeMember("WorkingDirectory",BindingFlags.SetProperty,null,shortcut,new object[]{target});
        shortcutType.InvokeMember("IconLocation",BindingFlags.SetProperty,null,shortcut,new object[]{launcher+",0"});
        shortcutType.InvokeMember("Description",BindingFlags.SetProperty,null,shortcut,new object[]{"LAKIS Studio 실행"});
        shortcutType.InvokeMember("Save",BindingFlags.InvokeMethod,null,shortcut,null);
        status("바탕화면 바로가기 생성: LAKIS");
    }
    private static void StopOwned(string target){string prefix=Path.GetFullPath(target).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;foreach(Process p in Process.GetProcesses()){try{if(p.MainModule.FileName.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)){p.Kill();p.WaitForExit(5000);}}catch{}finally{p.Dispose();}}}
}
