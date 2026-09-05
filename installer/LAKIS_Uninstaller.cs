using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class LakisUninstaller
{
    private static void StopOwnedProcesses(string target)
    {
        string prefix = Path.GetFullPath(target).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        foreach (Process process in Process.GetProcesses())
        {
            try
            {
                if (process.Id == Process.GetCurrentProcess().Id) continue;
                string executable = process.MainModule.FileName;
                if (!executable.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) continue;
                process.Kill();
                process.WaitForExit(5000);
            }
            catch { }
            finally { process.Dispose(); }
        }
    }

    private static void RemoveDesktopShortcut()
    {
        try
        {
            string shortcut = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "LAKIS.lnk");
            if (File.Exists(shortcut)) File.Delete(shortcut);
        }
        catch { }
    }

    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length >= 2 && String.Equals(args[0], "--cleanup", StringComparison.OrdinalIgnoreCase))
        {
            string cleanupTarget = Path.GetFullPath(args[1]).TrimEnd(Path.DirectorySeparatorChar);
            try
            {
                System.Threading.Thread.Sleep(1500);
                StopOwnedProcesses(cleanupTarget);
                RemoveDesktopShortcut();
                for (int attempt = 0; attempt < 30 && Directory.Exists(cleanupTarget); attempt++)
                {
                    try { Directory.Delete(cleanupTarget, true); }
                    catch (IOException) { System.Threading.Thread.Sleep(1000); }
                    catch (UnauthorizedAccessException) { System.Threading.Thread.Sleep(1000); }
                }
                return Directory.Exists(cleanupTarget) ? 1 : 0;
            }
            catch { return 1; }
        }
        string target = Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory).TrimEnd(Path.DirectorySeparatorChar);
        bool headless = Array.Exists(args, value => String.Equals(value, "--headless", StringComparison.OrdinalIgnoreCase));
        if (!headless)
        {
            Application.EnableVisualStyles();
            DialogResult answer = MessageBox.Show(
                "LAKIS를 삭제하시겠습니까?\n생성 이미지를 보관하려면 먼저 ComfyUI\\output 폴더를 복사해 주세요.",
                "LAKIS 제거", MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
            if (answer != DialogResult.Yes) return 2;
        }
        try
        {
            StopOwnedProcesses(target);
            RemoveDesktopShortcut();
            string temporary = Path.Combine(Path.GetTempPath(), "LAKIS_Uninstall_" + Guid.NewGuid().ToString("N") + ".exe");
            File.Copy(Application.ExecutablePath, temporary, true);
            Process.Start(new ProcessStartInfo(temporary, "--cleanup \"" + target + "\"")
            {
                CreateNoWindow = true,
                UseShellExecute = false,
                WorkingDirectory = Path.GetTempPath()
            });
            return 0;
        }
        catch (Exception error)
        {
            if (headless) Console.Error.WriteLine(error);
            else MessageBox.Show(error.Message, "LAKIS 제거 오류", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
