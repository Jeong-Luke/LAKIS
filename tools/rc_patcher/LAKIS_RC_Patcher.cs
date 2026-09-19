using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal sealed class PatcherForm : Form
{
    readonly Label current = new Label(), package = new Label(), status = new Label();
    readonly TextBox log = new TextBox(); readonly Button choose = new Button(), apply = new Button(), restore = new Button(), chooseRoot = new Button();
    string root, zip; readonly JavaScriptSerializer json = new JavaScriptSerializer();

    internal PatcherForm()
    {
        Text="LAKIS RC Patcher — TESTER ONLY"; ClientSize=new Size(620,500); StartPosition=FormStartPosition.CenterScreen;
        BackColor=Color.FromArgb(16,19,31); ForeColor=Color.FromArgb(232,235,248); Font=new Font("Segoe UI",10F); FormBorderStyle=FormBorderStyle.FixedDialog; MaximizeBox=false;
        Controls.Add(new Label{Left=28,Top=24,Width=430,Height=38,Text="LAKIS RC Patcher",Font=new Font("Segoe UI",20F,FontStyle.Bold),ForeColor=Color.FromArgb(164,132,255)});
        Controls.Add(new Label{Left=455,Top=31,Width=125,Height=28,Text="TESTER ONLY",TextAlign=ContentAlignment.MiddleCenter,BackColor=Color.FromArgb(58,39,91),ForeColor=Color.FromArgb(255,151,210),Font=new Font("Segoe UI",9F,FontStyle.Bold)});
        current.SetBounds(30,82,550,42); package.SetBounds(30,132,550,82); status.SetBounds(30,405,550,28); status.ForeColor=Color.FromArgb(178,158,255);
        Setup(choose,"ZIP 파일 선택",30,226,150); Setup(chooseRoot,"LAKIS 설치 폴더",195,226,165); Setup(apply,"패치 적용",375,226,100); Setup(restore,"이전 상태로 복원",490,226,100);
        log.SetBounds(30,278,560,116); log.Multiline=true; log.ReadOnly=true; log.ScrollBars=ScrollBars.Vertical; log.BackColor=Color.FromArgb(10,12,20); log.ForeColor=Color.FromArgb(196,202,223); log.BorderStyle=BorderStyle.FixedSingle;
        Controls.AddRange(new Control[]{current,package,status,choose,chooseRoot,apply,restore,log});
        choose.Click+=(s,e)=>SelectZip(); chooseRoot.Click+=(s,e)=>SelectRoot(); apply.Click+=(s,e)=>Apply(); restore.Click+=(s,e)=>Restore();
        root=FindRoot(AppDomain.CurrentDomain.BaseDirectory); RefreshCurrent(); apply.Enabled=false;
    }
    void Setup(Button b,string text,int x,int y,int w){b.Text=text;b.SetBounds(x,y,w,38);b.FlatStyle=FlatStyle.Flat;b.FlatAppearance.BorderColor=Color.FromArgb(124,91,230);b.ForeColor=Color.White;b.BackColor=Color.FromArgb(29,33,49);}
    string FindRoot(string start){var d=new DirectoryInfo(start);while(d!=null){if(File.Exists(Path.Combine(d.FullName,"LAKIS.exe"))&&Directory.Exists(Path.Combine(d.FullName,"ComfyUI")))return d.FullName;d=d.Parent;}return "";}
    void RefreshCurrent(){current.Text="현재 설치\r\n"+(String.IsNullOrEmpty(root)?"선택되지 않음":root+"  ·  LAKIS v"+ReadVersion(root));}
    string ReadVersion(string r){try{return File.ReadAllText(Path.Combine(r,"VERSION"),Encoding.UTF8).Trim().TrimStart('v');}catch{return "확인 불가";}}
    string Engine()
    {
        string sidecar=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"rc_patch.py");
        if(File.Exists(sidecar))return sidecar;
        string folder=Path.Combine(Path.GetTempPath(),"LAKIS_RC_Patcher");
        Directory.CreateDirectory(folder);
        string embedded=Path.Combine(folder,"rc_patch.py");
        using(Stream input=Assembly.GetExecutingAssembly().GetManifestResourceStream("LAKIS.RCPatchEngine"))
        {
            if(input==null)throw new FileNotFoundException("내장 RC 패치 엔진을 찾을 수 없습니다.");
            using(FileStream output=new FileStream(embedded,FileMode.Create,FileAccess.Write,FileShare.Read))input.CopyTo(output);
        }
        return embedded;
    }
    string Python(){if(!String.IsNullOrEmpty(root)){string p=Path.Combine(root,"python_embeded","python.exe");if(File.Exists(p))return p;} string sibling=Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"..","python_embeded","python.exe"));if(File.Exists(sibling))return sibling;return "python";}
    string Run(string args){var psi=new ProcessStartInfo(Python(),"-s \""+Engine()+"\" "+args){UseShellExecute=false,RedirectStandardOutput=true,RedirectStandardError=true,CreateNoWindow=true,StandardOutputEncoding=Encoding.UTF8};using(var p=Process.Start(psi)){string o=p.StandardOutput.ReadToEnd(),e=p.StandardError.ReadToEnd();p.WaitForExit();if(p.ExitCode!=0)throw new Exception(String.IsNullOrWhiteSpace(o)?e:o);return o.Trim();}}
    void SelectRoot(){using(var f=new FolderBrowserDialog()){f.Description="LAKIS 설치 폴더 선택";if(f.ShowDialog()==DialogResult.OK){root=f.SelectedPath;RefreshCurrent();}}}
    void SelectZip(){using(var f=new OpenFileDialog()){f.Filter="LAKIS Team Patch (*.zip)|*.zip";if(f.ShowDialog()!=DialogResult.OK)return;try{zip=f.FileName;var d=json.DeserializeObject(Run("inspect \""+zip+"\"")) as System.Collections.Generic.Dictionary<string,object>;package.Text=String.Format("테스트 패키지\r\n{0}  ·  Internal {1}  ·  Base v{2}\r\nChanged files: {3}  ·  Removed: {4}",d["display_version"],d["internal_version"],d["base_version"],d["files"],d["delete"]);apply.Enabled=!String.IsNullOrEmpty(root);status.Text="패키지 검증 완료";}catch(Exception ex){Fail(ex);}}}
    void Apply(){if(String.IsNullOrEmpty(zip)||String.IsNullOrEmpty(root))return;if(MessageBox.Show("LAKIS와 ComfyUI를 종료했는지 확인해 주세요.\n선택한 로컬 RC 패치를 적용할까요?","LAKIS RC Patcher",MessageBoxButtons.YesNo,MessageBoxIcon.Warning)!=DialogResult.Yes)return;try{Busy(true);log.Text=Run("apply \""+zip+"\" \""+root+"\"");status.Text="PATCH APPLIED";}catch(Exception ex){Fail(ex);}finally{Busy(false);}}
    void Restore(){if(String.IsNullOrEmpty(root))return;if(MessageBox.Show("가장 최근 RC 패치 이전 상태로 복원할까요?","LAKIS RC Patcher",MessageBoxButtons.YesNo,MessageBoxIcon.Warning)!=DialogResult.Yes)return;try{Busy(true);log.Text=Run("rollback \""+root+"\"");status.Text="ROLLBACK COMPLETE";}catch(Exception ex){Fail(ex);}finally{Busy(false);}}
    void Busy(bool value){choose.Enabled=chooseRoot.Enabled=apply.Enabled=restore.Enabled=!value;Application.DoEvents();}
    void Fail(Exception ex){status.Text="작업을 완료하지 못했습니다.";log.Text=ex.Message;MessageBox.Show(ex.Message,"LAKIS RC Patcher",MessageBoxButtons.OK,MessageBoxIcon.Error);}
}
internal static class Program { [STAThread] static void Main(){Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new PatcherForm());} }
