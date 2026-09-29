"""Run the real Setup entry point and ZIP/copy/cleanup code on long paths."""
import os
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import shutil
import tempfile
import threading
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
CSC = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
PROBE = r'''
using System;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
internal static class LongPathProbe {
    private static object Call(string name, params object[] args) {
        return typeof(SafeInstaller).GetMethod(name, BindingFlags.NonPublic | BindingFlags.Static).Invoke(null, args);
    }
    private static int Main(string[] args) {
        // Exercise production startup before any System.IO path handling.
        var main = typeof(SafeSetupForm).GetMethod("Main", BindingFlags.NonPublic | BindingFlags.Static);
        if ((int)main.Invoke(null, new object[]{new[]{"--headless"}}) != 2) return 10;
        if(args[3] == "root") {
            try { SafeInstaller.InstallFresh(Path.GetPathRoot(args[0]), _=>{throw new Exception("Must not build");}, _=>{}); return 30; }
            catch(InvalidOperationException) { Console.WriteLine("ROOT_BLOCKED"); return 0; }
        }
        if(args[3] == "cache" || args[3] == "sevenzip") {
            try {
            Environment.SetEnvironmentVariable("TEMP",args[1]);
            Environment.SetEnvironmentVariable("TMP",args[1]);
            Environment.SetEnvironmentVariable("LOCALAPPDATA",args[4]);
            string cache=(string)Call("InstallerCache");
            if(cache.Length<=260) return 31;
            if(args[3] == "cache") {
                string hash;byte[] bytes=Encoding.ASCII.GetBytes("verified payload");
                using(var digest=SHA256.Create())hash=BitConverter.ToString(digest.ComputeHash(bytes)).Replace("-","");
                string result=(string)Call("Fetch",new DownloadItem("payload.bin",args[0],hash,null,bytes.Length),cache,(Action<string>)(_=>{}));
                if(File.ReadAllText(result)!="verified payload")return 32;
                Console.WriteLine("LONG_CACHE_FETCH_PASS");
            } else {
                Call("Extract7z",args[0],args[2]);
                string extracted=(string)Call("FileSystemPath",Path.Combine(args[2],"ComfyUI_windows_portable","test.txt"));
                if(File.ReadAllText(extracted)!="verified payload")return 33;
                Console.WriteLine("LONG_CACHE_7ZR_PASS");
            }
            Call("DeleteTree",cache);return 0;
            } catch(Exception error) {
                var cause=error is TargetInvocationException ? error.InnerException : error;
                Console.Error.WriteLine(cause.GetType().FullName + ": " + cause.Message);
                return 34;
            }
        }
        try {
            Call("ExtractZip", args[0], args[1]);
            if(args[3] == "reject") return 11;
            Call("CopyTree", args[1], args[2]);
            string[] files = Directory.GetFiles(@"\\?\" + args[2], "*", SearchOption.AllDirectories);
            if(files.Length != 1 || File.ReadAllText(files[0]) != "verified payload") return 12;
            Console.WriteLine("LONG_PATH_PASS " + files[0].Length);
            Call("DeleteTree", args[1]);
            Call("DeleteTree", args[2]);
            if(Directory.Exists(args[1]) || Directory.Exists(args[2])) return 13;
        } catch(TargetInvocationException error) {
            if(args[3] != "reject" || !(error.InnerException is IOException)) {
                Console.Error.WriteLine(error.InnerException.GetType().FullName + ": " + error.InnerException.Message);
                return 20;
            }
            Console.WriteLine("UNSAFE_PATH_REJECTED");
        }
        return 0;
    }
}
'''


@unittest.skipUnless(CSC.is_file(), 'Windows .NET Framework compiler required')
class SetupLongPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        probe = cls.root/'Probe.cs'
        probe.write_text(PROBE, encoding='utf-8')
        cls.exe = cls.root/'LongPathProbe.exe'
        cls.sevenzip = ROOT/'.safe-installer-build/7zr.exe'
        resources=[]
        if cls.sevenzip.is_file():
            if hashlib.sha256(cls.sevenzip.read_bytes()).hexdigest().upper() != 'AD4C82FADCBDF93C03B4FC440F300509C7D60C5C2F4D183E35D9D70D6957037D':
                raise RuntimeError('Unverified 7zr fixture')
            resources=['/resource:'+str(cls.sevenzip)+',LAKIS.7zr']
        result = subprocess.run([str(CSC), '/nologo', '/target:exe', '/main:LongPathProbe',
            '/out:' + str(cls.exe), '/reference:System.Windows.Forms.dll',
            '/reference:System.Drawing.dll', '/reference:System.IO.Compression.dll',
            '/reference:System.IO.Compression.FileSystem.dll', str(ROOT/'installer/SplashArtwork.cs'),
            str(ROOT/'installer/Setup_LAKIS_Safe.cs'), str(probe)]+resources, capture_output=True)
        if result.returncode:
            cls.temporary.cleanup()
            raise RuntimeError(result.stdout.decode(errors='replace'))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def probe(self, member, long_root=False, reject=False):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            root = Path(directory)
            base = root
            if long_root:
                base = base/('사용자 지정 TEMP_' + 'x'*70)/('cache_' + 'y'*75)
            archive = root/'source.zip'
            with zipfile.ZipFile(archive, 'w') as package:
                package.writestr(member, b'verified payload')
            extracted, copied = base/'extract', base/'copy'
            expected_length = len(str(copied/member))
            if long_root:
                self.assertGreater(expected_length, 260)
            result = subprocess.run([str(self.exe), str(archive), str(extracted), str(copied),
                                     'reject' if reject else 'valid'], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertIn(b'UNSAFE_PATH_REJECTED' if reject else b'LONG_PATH_PASS', result.stdout)
            if reject:
                self.assertFalse(any(p.name == 'escaped.txt' for p in root.rglob('*')))
            return expected_length

    def test_long_temp_extract_copy_and_cleanup(self):
        self.probe('LAKIS-'+'a'*40+'/src/custom_nodes/ComfyUI-KR-Camera-PromptStudio-Bridge/web/kr_camera_prompt_studio_bridge.js', True)

    def test_over_400_characters_and_unicode(self):
        length = self.probe(('긴경로_'+'z'*90)+'/nested/'+('w'*90)+'/파일.txt', True)
        self.assertGreater(length, 400)

    def test_short_paths_unchanged(self):
        self.probe('package/file.txt')

    def test_zip_traversal_still_rejected(self):
        for name in ['../escaped.txt', 'package/../../escaped.txt', '..\\escaped.txt',
                     '/escaped.txt', 'C:/escaped.txt']:
            with self.subTest(name=name):
                self.probe(name, reject=True)

    def test_ambiguous_windows_zip_paths_rejected(self):
        for name in ['package/file.txt:stream', 'package/.. /escaped.txt', 'package./escaped.txt']:
            with self.subTest(name=name):
                self.probe(name, reject=True)

    def test_drive_root_rejected_before_work(self):
        result=subprocess.run([str(self.exe),str(self.root),'unused','unused','root'],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        self.assertIn(b'ROOT_BLOCKED',result.stdout)

    def long_cache_probe(self, mode, first_arg):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            root=Path(directory);temp=root/('temp_'+'t'*100)/('cache_'+'c'*100)
            temp.mkdir(parents=True);destination=root/'output';local=root/'localappdata'
            if mode=='sevenzip':
                archive=temp/'portable.7z';shutil.copyfile(first_arg,archive);first_arg=archive
                destination=temp/'extraction'
                self.assertGreater(len(str(archive)),260)
                self.assertGreater(len(str(destination)),260)
            destination.mkdir()
            result=subprocess.run([str(self.exe),str(first_arg),str(temp),str(destination),mode,str(local)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            self.assertIn(b'LONG_CACHE_',result.stdout)
            tools=local/'LAKIS Studio/setup-tools'
            if tools.exists():self.assertEqual(list(tools.iterdir()),[])

    def test_long_temp_actual_http_fetch_and_hash(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_GET(self):
                payload=b'verified payload';self.send_response(200)
                self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:self.long_cache_probe('cache','http://127.0.0.1:'+str(server.server_port)+'/fixture')
        finally:server.shutdown();server.server_close();thread.join(timeout=5)

    def test_long_temp_actual_embedded_7zr_launch_and_extract(self):
        if not self.sevenzip.is_file():self.skipTest('Verified build 7zr is required for native tool integration')
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            root=Path(directory);content=root/'ComfyUI_windows_portable';content.mkdir()
            (content/'test.txt').write_text('verified payload',encoding='ascii')
            archive=root/'fixture.7z'
            result=subprocess.run([str(self.sevenzip),'a',str(archive),'ComfyUI_windows_portable'],cwd=root,capture_output=True)
            self.assertEqual(result.returncode,0)
            self.long_cache_probe('sevenzip',archive)


if __name__ == '__main__':
    unittest.main(verbosity=2)
