"""Execute the actual Setup source contract without downloading/installing anything."""
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMPILER = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
PROBE = r'''
using System;
using System.Reflection;
internal static class PinProbe {
    private static int Main(string[] args) {
        var method = typeof(SafeInstaller).GetMethod("SourceArchive", BindingFlags.NonPublic | BindingFlags.Static);
        foreach (string prefix in new[] {"LAKIS-", "LAKIS-repair-"}) {
            try {
                var item = (DownloadItem)method.Invoke(null, new object[] {prefix});
                if (args.Length == 0) return 10;
                if (item.Sha != new string('B', 64) ||
                    item.Url != "https://api.github.com/repos/Jeong-Luke/LAKIS/zipball/" + new string('a', 40) ||
                    item.Name != prefix + new string('a', 40) + ".zip") return 11;
            } catch (TargetInvocationException error) {
                if (args.Length != 0 || !(error.InnerException is InvalidOperationException)) return 12;
            }
        }
        try {
            var webview = (DownloadItem)typeof(SafeInstaller).GetMethod("WebView2Archive", BindingFlags.NonPublic | BindingFlags.Static).Invoke(null,null);
            if(args.Length==0 || webview.Sha!=new string('C',64) || webview.Bytes!=99 || webview.Url!="https://example.invalid/webview")return 13;
        } catch(TargetInvocationException error) {
            if(args.Length!=0 || !(error.InnerException is InvalidOperationException))return 14;
        }
        var versionCheck=typeof(SafeInstaller).GetMethod("IsInstalledWebView2Version",BindingFlags.NonPublic|BindingFlags.Static);
        foreach(var value in new[]{"","0.0.0.0"," 0.0.0.0 ","not-a-version","1.2","1.2.3.999999999999999"})
            if((bool)versionCheck.Invoke(null,new object[]{value}))return 15;
        if(!(bool)versionCheck.Invoke(null,new object[]{"160.0.4430.69"}))return 16;
        Console.WriteLine("SOURCE_PIN_CONTRACT_PASS");
        return 0;
    }
}
'''

FETCH_PROBE = r'''
using System;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
internal static class PinProbe {
    private static int Main(string[] args) {
        string root=args[0], url=args[1], hash;
        byte[] payload=Encoding.ASCII.GetBytes("correct bytes");
        using(var sha=SHA256.Create())hash=BitConverter.ToString(sha.ComputeHash(payload)).Replace("-","");
        var fetch=typeof(SafeInstaller).GetMethod("Fetch",BindingFlags.NonPublic|BindingFlags.Static);
        Action<string> status=_=>{};
        File.WriteAllBytes(Path.Combine(root,"complete.bin.part"),payload);
        var complete=new DownloadItem("complete.bin","http://127.0.0.1:1/not-requested",hash,null,payload.Length);
        fetch.Invoke(null,new object[]{complete,root,status});
        if(!File.Exists(Path.Combine(root,"complete.bin")))return 30;
        File.WriteAllText(Path.Combine(root,"unknown.bin.part"),"corrupt oversized partial content");
        var unknown=new DownloadItem("unknown.bin",url,hash);
        fetch.Invoke(null,new object[]{unknown,root,status});
        if(File.ReadAllText(Path.Combine(root,"unknown.bin"))!="correct bytes")return 31;
        File.WriteAllText(Path.Combine(root,"known.bin.part"),"wrong content");
        var known=new DownloadItem("known.bin",url,hash,null,payload.Length);
        fetch.Invoke(null,new object[]{known,root,status});
        if(File.ReadAllText(Path.Combine(root,"known.bin"))!="correct bytes")return 32;
        File.WriteAllText(Path.Combine(root,"prefix.bin.part"),"bad");
        var prefix=new DownloadItem("prefix.bin",url+"/prefix",hash,null,payload.Length);
        try { fetch.Invoke(null,new object[]{prefix,root,status}); return 33; }
        catch(TargetInvocationException error) { if(!(error.InnerException is IOException))return 34; }
        // Re-running deletes the failed cached download and fetches valid bytes.
        fetch.Invoke(null,new object[]{prefix,root,status});
        if(File.ReadAllText(Path.Combine(root,"prefix.bin"))!="correct bytes")return 35;
        Console.WriteLine("SOURCE_PIN_CONTRACT_PASS");
        return 0;
    }
}
'''

STAGING_PROBE = r'''
using System;
using System.IO;
internal static class PinProbe {
    private static int Main(string[] args) {
        string root=args[0], target=Path.Combine(root,"success"), stageSeen=null;
        SafeInstaller.InstallFresh(target, stage=>{
            stageSeen=stage; Directory.CreateDirectory(stage);
            File.WriteAllText(Path.Combine(stage,"payload.txt"),"complete");
        },_=>{});
        if(File.ReadAllText(Path.Combine(target,"payload.txt"))!="complete" || Directory.Exists(stageSeen))return 20;
        target=Path.Combine(root,"failed");
        try {
            SafeInstaller.InstallFresh(target, stage=>{
                stageSeen=stage; Directory.CreateDirectory(stage);
                File.WriteAllText(Path.Combine(stage,"partial.txt"),"partial");
                throw new IOException("simulated interruption");
            },_=>{});
            return 21;
        } catch(InvalidOperationException) {}
        if(Directory.GetFileSystemEntries(target).Length!=0 || !File.Exists(Path.Combine(stageSeen,"partial.txt")))return 22;
        target=Path.Combine(root,"conflict");
        try {
            SafeInstaller.InstallFresh(target, stage=>{
                Directory.CreateDirectory(stage); File.WriteAllText(Path.Combine(stage,"payload.txt"),"complete");
                File.WriteAllText(Path.Combine(target,"user.txt"),"preserve");
            },_=>{});
            return 23;
        } catch(InvalidOperationException) {}
        if(File.ReadAllText(Path.Combine(target,"user.txt"))!="preserve" || File.Exists(Path.Combine(target,"payload.txt")))return 24;
        Console.WriteLine("SOURCE_PIN_CONTRACT_PASS");
        return 0;
    }
}
'''

REPAIR_PROBE = r'''
using System;
using System.IO;
using System.Reflection;
internal static class PinProbe {
    private static int Main(string[] args) {
        string source=Path.Combine(args[0],"source"),target=Path.Combine(args[0],"installed");
        Directory.CreateDirectory(source);Directory.CreateDirectory(target);
        foreach(string relative in new[]{"settings.json","civitai/token.txt","wildcards/user.txt","backups/one.zip","stats/data.json","logs/one.log","cache/db.sqlite","model_cache/index.json"}) {
            string input=Path.Combine(source,relative),output=Path.Combine(target,relative);
            Directory.CreateDirectory(Path.GetDirectoryName(input));Directory.CreateDirectory(Path.GetDirectoryName(output));
            File.WriteAllText(input,"package");File.WriteAllText(output,"user");
        }
        File.WriteAllText(Path.Combine(target,"custom-user-file.txt"),"keep");
        File.WriteAllText(Path.Combine(target,"code.py"),"old");File.WriteAllText(Path.Combine(source,"code.py"),"new");
        typeof(SafeInstaller).GetMethod("CopyLoraManagerForRepair",BindingFlags.NonPublic|BindingFlags.Static).Invoke(null,new object[]{source,target});
        foreach(string file in Directory.GetFiles(target,"*",SearchOption.AllDirectories)) {
            string name=Path.GetFileName(file), expected=name=="code.py"?"new":name=="custom-user-file.txt"?"keep":"user";
            if(File.ReadAllText(file)!=expected)return 40;
        }
        Console.WriteLine("SOURCE_PIN_CONTRACT_PASS");return 0;
    }
}
'''


@unittest.skipUnless(COMPILER.is_file(), 'Windows .NET Framework compiler required')
class SetupSourcePinTests(unittest.TestCase):
    def run_probe(self, pinned, probe=PROBE, extra_args=None):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = (ROOT / 'installer/Setup_LAKIS_Safe.cs').read_text(encoding='utf-8-sig')
            if pinned:
                source = re.sub(r'private const string Revision = "[^"]+";',
                                'private const string Revision = "' + 'a' * 40 + '";', source)
                source = re.sub(r'private const string SourceArchiveSha256 = "[^"]+";',
                                'private const string SourceArchiveSha256 = "' + 'B' * 64 + '";', source)
                source = re.sub(r'private const string WebView2BootstrapperUrl = "[^"]+";',
                                'private const string WebView2BootstrapperUrl = "https://example.invalid/webview";', source)
                source = re.sub(r'private const string WebView2BootstrapperSha256 = "[^"]+";',
                                'private const string WebView2BootstrapperSha256 = "' + 'C' * 64 + '";', source)
                source = source.replace('private const long WebView2BootstrapperBytes = 0;',
                                        'private const long WebView2BootstrapperBytes = 99;')
            (temporary / 'Setup.cs').write_text(source, encoding='utf-8')
            (temporary / 'Probe.cs').write_text(probe, encoding='utf-8')
            output = temporary / 'PinProbe.exe'
            compiled = subprocess.run([
                str(COMPILER), '/nologo', '/target:exe', '/main:PinProbe', '/out:' + str(output),
                '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
                str(ROOT / 'installer/SplashArtwork.cs'), str(temporary / 'Setup.cs'), str(temporary / 'Probe.cs'),
            ], capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout.decode(errors='replace'))
            arguments = [str(temporary)] + (extra_args or []) if probe in (STAGING_PROBE, FETCH_PROBE, REPAIR_PROBE) else (['pinned'] if pinned else [])
            result = subprocess.run([str(output)] + arguments, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertIn(b'SOURCE_PIN_CONTRACT_PASS', result.stdout)

    def test_unpinned_setup_cannot_construct_network_source(self):
        self.run_probe(False)

    def test_install_and_repair_share_exact_revision_and_sha(self):
        self.run_probe(True)

    def test_fresh_install_promotion_failure_and_target_conflict(self):
        self.run_probe(False, STAGING_PROBE)

    def test_lora_repair_preserves_user_state_and_restores_code(self):
        source=(ROOT/'installer/Setup_LAKIS_Safe.cs').read_text(encoding='utf-8-sig')
        self.assertIn('InstallZip(LoraManager,cache,Path.Combine(custom,LoraManager.Destination),status)',source)
        self.assertIn('if(Object.ReferenceEquals(item,LoraManager)&&Directory.Exists(destination))CopyLoraManagerForRepair(source,destination)',source)
        self.run_probe(False,REPAIR_PROBE)

    def test_actual_setup_fetch_recovers_complete_and_corrupt_partials(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_GET(self):
                offset = self.headers.get('Range')
                requests.append(offset)
                resumed_prefix = self.path.endswith('/prefix') and offset
                self.send_response(206 if resumed_prefix else (416 if offset else 200))
                payload = b'rect bytes' if resumed_prefix else (b'' if offset else b'correct bytes')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            self.run_probe(False, FETCH_PROBE, [f'http://127.0.0.1:{server.server_port}/fixture'])
            self.assertEqual(requests, ['bytes=33-', None, None, 'bytes=3-', None])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
