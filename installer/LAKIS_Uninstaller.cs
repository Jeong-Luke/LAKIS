using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

internal sealed class UninstallForm : Form
{
    private readonly CenterCropPictureBox artwork = new CenterCropPictureBox();
    private readonly List<Image> frames = new List<Image>();
    private readonly Timer timer = new Timer();
    private int frameIndex;

    internal UninstallForm(string root)
    {
        Text = "LAKIS 삭제";
        ClientSize = new Size(760, 430);
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(12, 14, 22);
        ForeColor = Color.White;
        Font = new Font("Segoe UI", 10F);
        DoubleBuffered = true;
        LakisWindowDrag.Enable(this);

        LoadArtwork();
        artwork.SetBounds(400, 48, 336, 358);
        artwork.BackColor = Color.FromArgb(18, 22, 38);
        if (frames.Count > 0) artwork.Image = frames[0];
        timer.Interval = 5000;
        timer.Tick += (_, __) => {
            if (frames.Count < 2) return;
            frameIndex = (frameIndex + 1) % frames.Count;
            artwork.Image = frames[frameIndex];
            artwork.Invalidate();
        };
        timer.Start();

        var logo = new PictureBox { Left=42, Top=42, Width=54, Height=54, SizeMode=PictureBoxSizeMode.Zoom, Image=Icon.ExtractAssociatedIcon(Application.ExecutablePath).ToBitmap() };
        var title = new Label { Left=112, Top=43, Width=280, Height=34, Text="L A K I S", Font=new Font("Segoe UI",20F,FontStyle.Bold), ForeColor=Color.FromArgb(225,229,255) };
        var subtitle = new Label { Left=114, Top=78, Width=260, Height=25, Text="Studio", Font=new Font("Segoe UI",11F,FontStyle.Bold), ForeColor=Color.FromArgb(171,178,203) };
        var message = new Label { Left=43, Top=174, Width=315, Height=70, Text="LAKIS를 삭제하시겠습니까?\n생성 이미지를 보관하려면 먼저\nComfyUI\\output 폴더를 복사해 주세요.", ForeColor=Color.FromArgb(150,158,181), Font=new Font("Segoe UI",9F) };
        var cancel = new Button { Left=43, Top=306, Width=145, Height=38, Text="취소", DialogResult=DialogResult.Cancel };
        var remove = new Button { Left=201, Top=306, Width=157, Height=38, Text="삭제", DialogResult=DialogResult.Yes };
        foreach (Button button in new[] { cancel, remove }) {
            button.FlatStyle=FlatStyle.Flat; button.FlatAppearance.BorderSize=0;
            button.BackColor=Color.FromArgb(111,82,225); button.ForeColor=Color.White;
            button.Font=new Font("Segoe UI",9F,FontStyle.Bold); button.Cursor=Cursors.Hand;
        }
        remove.BackColor = Color.FromArgb(176, 55, 65);
        var close = new Button { Left=712, Top=0, Width=48, Height=42, Text="\uE8BB", Font=new Font("Segoe MDL2 Assets",9F), ForeColor=Color.FromArgb(205,211,225), BackColor=Color.Transparent, FlatStyle=FlatStyle.Flat, TabStop=false, Cursor=Cursors.Hand, DialogResult=DialogResult.Cancel };
        close.FlatAppearance.BorderSize=0;
        close.FlatAppearance.MouseOverBackColor=Color.FromArgb(196,43,28);
        string version="7.2.4";
        try { string path=Path.Combine(root,"VERSION"); if(File.Exists(path)) version=File.ReadAllText(path).Trim(); } catch { }
        var copyright = new Label { Left=43, Top=399, Width=335, Height=18, Text="© 2026 Luke Jeong. All rights reserved. · LAKIS v"+version, ForeColor=Color.FromArgb(104,112,137), Font=new Font("Segoe UI",8F) };

        Controls.AddRange(new Control[] { artwork, logo, title, subtitle, message, cancel, remove, copyright, close });
        close.BringToFront();
        AcceptButton=remove;
        CancelButton=cancel;
        FormClosed += (_, __) => { timer.Stop(); foreach(Image image in frames) image.Dispose(); };
    }

    private void LoadArtwork()
    {
        Assembly assembly=Assembly.GetExecutingAssembly();
        foreach(string name in new[]{"LAKIS.Splash1","LAKIS.Splash2"})
            using(Stream stream=assembly.GetManifestResourceStream(name))
                if(stream!=null) frames.Add(new Bitmap(stream));
    }
}

internal static class LakisUninstaller
{
    private static void StopOwnedProcesses(string target)
    {
        string prefix=Path.GetFullPath(target).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
        foreach(Process process in Process.GetProcesses())
        {
            try { if(process.Id!=Process.GetCurrentProcess().Id && process.MainModule.FileName.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)) { process.Kill(); process.WaitForExit(5000); } }
            catch { }
            finally { process.Dispose(); }
        }
    }

    private static void RemoveDesktopShortcut()
    {
        try { string shortcut=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),"LAKIS.lnk"); if(File.Exists(shortcut)) File.Delete(shortcut); }
        catch { }
    }

    [STAThread]
    private static int Main(string[] args)
    {
        if(args.Length>=2 && String.Equals(args[0],"--cleanup",StringComparison.OrdinalIgnoreCase))
        {
            string cleanupTarget=Path.GetFullPath(args[1]).TrimEnd(Path.DirectorySeparatorChar);
            try {
                System.Threading.Thread.Sleep(1500); StopOwnedProcesses(cleanupTarget); RemoveDesktopShortcut();
                for(int attempt=0; attempt<30 && Directory.Exists(cleanupTarget); attempt++)
                    try { Directory.Delete(cleanupTarget,true); } catch(IOException) { System.Threading.Thread.Sleep(1000); } catch(UnauthorizedAccessException) { System.Threading.Thread.Sleep(1000); }
                return Directory.Exists(cleanupTarget)?1:0;
            } catch { return 1; }
        }
        string target=Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory).TrimEnd(Path.DirectorySeparatorChar);
        bool headless=Array.Exists(args,value=>String.Equals(value,"--headless",StringComparison.OrdinalIgnoreCase));
        if(!headless) {
            Application.EnableVisualStyles();
            using(var form=new UninstallForm(target)) if(form.ShowDialog()!=DialogResult.Yes) return 2;
        }
        try {
            StopOwnedProcesses(target); RemoveDesktopShortcut();
            string temporary=Path.Combine(Path.GetTempPath(),"LAKIS_Uninstall_"+Guid.NewGuid().ToString("N")+".exe");
            File.Copy(Application.ExecutablePath,temporary,true);
            Process.Start(new ProcessStartInfo(temporary,"--cleanup \""+target+"\"") { CreateNoWindow=true, UseShellExecute=false, WorkingDirectory=Path.GetTempPath() });
            return 0;
        } catch(Exception error) {
            if(headless) Console.Error.WriteLine(error); else MessageBox.Show(error.Message,"LAKIS 삭제 오류",MessageBoxButtons.OK,MessageBoxIcon.Error);
            return 1;
        }
    }
}
