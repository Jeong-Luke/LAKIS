"""Execute the actual Setup source contract without downloading/installing anything."""
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
        var portable=(DownloadItem)typeof(SafeInstaller).GetField("Portable",BindingFlags.NonPublic|BindingFlags.Static).GetValue(null);
        if(portable.Name!="ComfyUI v0.21.1"||portable.Sha!="7C380D4309BBDA395366C49564EDF8996181FD45E61B6F353EA417F32BC3B970"||
           portable.Url!="https://github.com/Comfy-Org/ComfyUI/releases/download/v0.21.1/ComfyUI_windows_portable_nvidia.7z"||
           portable.Bytes!=2001582790)return 10;
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
        var cachePath=typeof(SafeInstaller).GetMethod("CachePath",BindingFlags.NonPublic|BindingFlags.Static);
        Action<string> status=_=>{};
        var complete=new DownloadItem("complete.bin","http://127.0.0.1:1/not-requested",hash,null,payload.Length);
        string completePath=(string)cachePath.Invoke(null,new object[]{root,complete});
        File.WriteAllBytes(completePath+".part",payload);
        fetch.Invoke(null,new object[]{complete,root,status});
        if(!File.Exists(completePath))return 30;
        File.Delete(completePath);
        var unknown=new DownloadItem("unknown.bin",url,hash);
        string unknownPath=(string)cachePath.Invoke(null,new object[]{root,unknown});
        File.WriteAllText(unknownPath+".part","corrupt oversized partial content");
        fetch.Invoke(null,new object[]{unknown,root,status});
        if(File.ReadAllText(unknownPath)!="correct bytes")return 31;
        File.Delete(unknownPath);
        var known=new DownloadItem("known.bin",url,hash,null,payload.Length);
        string knownPath=(string)cachePath.Invoke(null,new object[]{root,known});
        File.WriteAllText(knownPath+".part","wrong content");
        fetch.Invoke(null,new object[]{known,root,status});
        if(File.ReadAllText(knownPath)!="correct bytes")return 32;
        File.Delete(knownPath);
        var prefix=new DownloadItem("prefix.bin",url+"/prefix",hash,null,payload.Length);
        string prefixPath=(string)cachePath.Invoke(null,new object[]{root,prefix});
        File.WriteAllText(prefixPath+".part","bad");
        try { fetch.Invoke(null,new object[]{prefix,root,status}); return 33; }
        catch(TargetInvocationException error) { if(!(error.InnerException is IOException))return 34; }
        // Re-running deletes the failed cached download and fetches valid bytes.
        fetch.Invoke(null,new object[]{prefix,root,status});
        if(File.ReadAllText(prefixPath)!="correct bytes")return 35;
        Console.WriteLine("SOURCE_PIN_CONTRACT_PASS");
        return 0;
    }
}
'''

CONCURRENT_FETCH_PROBE = r'''
using System;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
internal static class PinProbe {
    private static int Main(string[] args) {
        string root=args[0],url=args[1],hash;
        byte[] payload=Encoding.ASCII.GetBytes("correct bytes");
        using(var sha=SHA256.Create())hash=BitConverter.ToString(sha.ComputeHash(payload)).Replace("-","");
        var fetch=typeof(SafeInstaller).GetMethod("Fetch",BindingFlags.NonPublic|BindingFlags.Static);
        var cachePath=typeof(SafeInstaller).GetMethod("CachePath",BindingFlags.NonPublic|BindingFlags.Static);
        var item=new DownloadItem("concurrent.bin",url,hash,null,payload.Length);
        Action<string> status=_=>{};
        Task first=Task.Run(()=>fetch.Invoke(null,new object[]{item,root,status}));
        Task second=Task.Run(()=>fetch.Invoke(null,new object[]{item,root,status}));
        Task.WaitAll(first,second);
        string path=(string)cachePath.Invoke(null,new object[]{root,item});
        if(!File.Exists(path)||File.ReadAllText(path)!="correct bytes"||File.Exists(path+".part"))return 50;
        Console.WriteLine("SOURCE_PIN_CONTRACT_PASS");return 0;
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

@unittest.skipUnless(COMPILER.is_file(), 'Windows .NET Framework compiler required')
class SetupSourcePinTests(unittest.TestCase):
    def run_probe(self, pinned, probe=PROBE, extra_args=None):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = (ROOT / 'installer/Setup_LAKIS_Safe.cs').read_text(encoding='utf-8-sig')
            (temporary / 'Setup.cs').write_text(source, encoding='utf-8')
            (temporary / 'Probe.cs').write_text(probe, encoding='utf-8')
            output = temporary / 'PinProbe.exe'
            compiled = subprocess.run([
                str(COMPILER), '/nologo', '/target:exe', '/main:PinProbe', '/out:' + str(output),
                '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                '/reference:System.Web.Extensions.dll', '/reference:System.IO.Compression.dll',
                '/reference:System.IO.Compression.FileSystem.dll',
                str(ROOT / 'installer/SplashArtwork.cs'),
                str(ROOT / 'installer/tests/RuntimeBundleInstallerStub.cs'),
                str(temporary / 'Setup.cs'), str(temporary / 'Probe.cs'),
            ], capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout.decode(errors='replace'))
            arguments = [str(temporary)] + (extra_args or []) if probe in (STAGING_PROBE, FETCH_PROBE, CONCURRENT_FETCH_PROBE) else []
            result = subprocess.run([str(output)] + arguments, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertIn(b'SOURCE_PIN_CONTRACT_PASS', result.stdout)

    def test_setup_keeps_the_pinned_portable_bootstrap(self):
        self.run_probe(False)

    def test_release_builder_pin_inputs_are_retained(self):
        source=(ROOT/'installer/Setup_LAKIS_Safe.cs').read_text(encoding='utf-8-sig')
        for declaration in ('private const string Revision =',
                            'private const string SourceArchiveSha256 =',
                            'private const string WebView2BootstrapperUrl =',
                            'private const string WebView2BootstrapperSha256 =',
                            'private const long WebView2BootstrapperBytes ='):
            self.assertIn(declaration,source)

    def test_fresh_install_promotion_failure_and_target_conflict(self):
        self.run_probe(False, STAGING_PROBE)

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
                # This case tests hash failure for a well-formed resumed response.
                # Missing/invalid Content-Range now triggers a safe fresh retry and
                # has separate pre-body rejection coverage in the boundary tests.
                payload = b'wrongbytes' if resumed_prefix else (b'' if offset else b'correct bytes')
                self.send_header('Content-Length', str(len(payload)))
                if resumed_prefix:
                    self.send_header('Content-Range', 'bytes 3-12/13')
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

    def test_actual_setup_serializes_concurrent_cache_writers(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_GET(self):
                requests.append(self.path)
                payload = b'correct bytes'
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            self.run_probe(False, CONCURRENT_FETCH_PROBE, [f'http://127.0.0.1:{server.server_port}/fixture'])
            self.assertEqual(requests, ['/fixture'])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
