"""Compile Setup manifest/cache/write contracts without downloading or installing."""
import copy
import hashlib
import importlib.util
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
COMPILER = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
MANIFEST_PROBE = r'''
using System;
using System.IO;
using System.Reflection;
internal static class PinProbe {
    private static int Main(string[] args) {
        var method = typeof(SafeInstaller).GetMethod("ReadRuntimeInstallManifest", BindingFlags.NonPublic | BindingFlags.Static);
        if (method == null) return 10;
        try {
            // Fresh Setup and Repair consume this same validated resource.
            // Exercise the reader twice, without launching either installation.
            foreach (string mode in new[] {"fresh", "repair"}) {
                string actual = (string)method.Invoke(null, null);
                if (args[1] != "accept") return 11;
                if (!String.Equals(actual, File.ReadAllText(args[2]), StringComparison.Ordinal)) return 12;
                Console.WriteLine("VALIDATED_" + mode);
            }
        } catch (TargetInvocationException error) {
            if (args[1] != "reject" || !(error.InnerException is InvalidDataException)) {
                Console.Error.WriteLine(error.InnerException.GetType().Name);
                return 13;
            }
        }
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

REPAIR_PROBE = r'''
using System;
using System.Collections.Generic;
using System.IO;
internal static class PinProbe {
    private static int Main(string[] args) {
        string target=Path.Combine(args[0],"installed");
        var before=new Dictionary<string,string>();
        foreach(string relative in new[]{
            "VERSION", "ComfyUI/LAKIS/STOP_AUTOMATION",
            ".lakis/settings.json", "ComfyUI/models/loras/user.safetensors",
            "ComfyUI/input/user.png", "ComfyUI/output/generated.png",
            "ComfyUI/user/default/workflows/user.json",
            "ComfyUI/custom_nodes/ComfyUI-Lora-Manager/settings.json",
            "ComfyUI/custom_nodes/ComfyUI-Lora-Manager/civitai/token.txt"
        }) {
            string path=Path.Combine(target,relative);
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            string contents=relative=="VERSION" ? "8.0.1" : "preserve: "+relative;
            File.WriteAllText(path,contents);before[path]=contents;
        }
        if(!SafeInstaller.IsExistingInstallation(target))return 40;
        int directories=Directory.GetDirectories(target,"*",SearchOption.AllDirectories).Length;
        try { SafeInstaller.Repair(target,_=>{}); return 41; }
        catch(InvalidOperationException) {}
        if(Directory.GetFiles(target,"*",SearchOption.AllDirectories).Length!=before.Count)return 42;
        if(Directory.GetDirectories(target,"*",SearchOption.AllDirectories).Length!=directories)return 43;
        foreach(var entry in before)
            if(File.ReadAllText(entry.Key)!=entry.Value)return 44;
        Console.WriteLine("SOURCE_PIN_CONTRACT_PASS");return 0;
    }
}
'''


@unittest.skipUnless(COMPILER.is_file(), 'Windows .NET Framework compiler required')
class SetupSourcePinTests(unittest.TestCase):
    def run_probe(self, probe, extra_args=None, *, manifest=None,
                  resource_name='LAKIS.RuntimeInstallManifest'):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            (temporary / 'Probe.cs').write_text(probe, encoding='utf-8')
            resources = []
            arguments = [str(temporary)] + (extra_args or [])
            if manifest is not None:
                embedded = temporary / 'manifest.json'
                embedded.write_text(manifest if isinstance(manifest, str) else json.dumps(manifest), encoding='utf-8')
                resources.append('/resource:' + str(embedded) + ',' + resource_name)
                arguments.append(str(embedded))
            output = temporary / 'PinProbe.exe'
            compiled = subprocess.run([
                str(COMPILER), '/nologo', '/target:exe', '/main:PinProbe', '/out:' + str(output),
                '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                '/reference:System.Web.Extensions.dll',
                '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
                str(ROOT / 'installer/UpdateProtocol.cs'), str(ROOT / 'installer/RuntimeBundleInstaller.cs'),
                str(ROOT / 'installer/SplashArtwork.cs'), str(ROOT / 'installer/Setup_LAKIS_Safe.cs'),
                str(temporary / 'Probe.cs'),
            ] + resources, capture_output=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout.decode(errors='replace'))
            result = subprocess.run([str(output)] + arguments, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertIn(b'SOURCE_PIN_CONTRACT_PASS', result.stdout)
            if probe == MANIFEST_PROBE and extra_args == ['accept']:
                self.assertIn(b'VALIDATED_fresh', result.stdout)
                self.assertIn(b'VALIDATED_repair', result.stdout)

    @staticmethod
    def pinned_manifest():
        """Synthetic bundle descriptor; real template model/source pins stay intact."""
        manifest = json.loads((ROOT / 'installer/cmd-installer-manifest.json').read_text(encoding='utf-8'))
        parts = (b'first runtime fixture part', b'second runtime fixture part')
        name = 'LAKIS_RuntimeBundle.zip'
        manifest['runtime_bundle'] = {
            'schema': 2, 'product': 'LAKIS', 'version': manifest['version'],
            'name': name, 'comfyui_version': '0.42.0', 'files': 1,
            'bytes': sum(map(len, parts)),
            'sha256': hashlib.sha256(b''.join(parts)).hexdigest().upper(),
            'manifest_sha256': hashlib.sha256(b'fixture runtime inventory').hexdigest().upper(),
            'parts': [{
                'name': f'{name}.part{index:03d}',
                'url': f'{manifest["release_base"]}/{name}.part{index:03d}',
                'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest().upper(),
            } for index, payload in enumerate(parts, 1)],
        }
        return manifest

    def reject_manifest_cases(self, cases):
        original = self.pinned_manifest()
        for path, value in cases:
            with self.subTest(path=path, value=value):
                manifest = copy.deepcopy(original)
                owner = manifest
                for key in path[:-1]:
                    owner = owner[key]
                owner[path[-1]] = value
                self.run_probe(MANIFEST_PROBE, ['reject'], manifest=manifest)

    def test_shared_fresh_repair_reader_accepts_exact_pinned_resource(self):
        self.run_probe(MANIFEST_PROBE, ['accept'], manifest=self.pinned_manifest())

    def test_reader_rejects_missing_empty_malformed_and_unpinned_manifest(self):
        template = json.loads((ROOT / 'installer/cmd-installer-manifest.json').read_text(encoding='utf-8'))
        for manifest in (None, '', ' \r\n ', '{', 'null', {}, template):
            with self.subTest(manifest=manifest):
                self.run_probe(MANIFEST_PROBE, ['reject'], manifest=manifest)
        self.run_probe(MANIFEST_PROBE, ['reject'], manifest=self.pinned_manifest(),
                       resource_name='LAKIS.WrongRuntimeInstallManifest')

    def test_reader_rejects_wrong_release_and_bundle_identity(self):
        self.reject_manifest_cases((
            (('schema',), 2), (('version',), '8.0.1'),
            (('runtime_bundle', 'schema'), 1),
            (('runtime_bundle', 'product'), 'LAKIS_DEV'),
            (('runtime_bundle', 'version'), '8.0.0'),
            (('runtime_bundle', 'name'), '../LAKIS_RuntimeBundle.zip'),
            (('runtime_bundle', 'name'), 'LAKIS_RuntimeBundle.7z'),
            (('runtime_bundle', 'comfyui_version'), ''),
        ))

    def test_reader_rejects_unpinned_or_invalid_download_model_and_bundle_hashes(self):
        paths = (
            ('base', 'sha256'), ('webview2', 'sha256'),
            ('runtime_bundle', 'sha256'), ('runtime_bundle', 'manifest_sha256'),
            ('runtime_bundle', 'parts', 0, 'sha256'),
            ('models', 0, 2), ('optional_animesharp', 2),
        )
        self.reject_manifest_cases(
            (path, value) for path in paths
            for value in ('BUILD_REQUIRES_PINNED_SHA256', 'A' * 63, 'G' * 64)
        )

    def test_reader_rejects_runtime_part_url_order_and_size_contract_violations(self):
        manifest = self.pinned_manifest()
        part = manifest['runtime_bundle']['parts'][0]
        self.reject_manifest_cases((
            (('runtime_bundle', 'parts'), []),
            (('runtime_bundle', 'parts'), [part] * 1000),
            (('runtime_bundle', 'parts'), list(reversed(manifest['runtime_bundle']['parts']))),
            (('runtime_bundle', 'parts', 0, 'name'), 'LAKIS_RuntimeBundle.zip.part002'),
            (('runtime_bundle', 'parts', 0, 'url'), part['url'].replace('/v8.0.2/', '/v8.0.0/')),
            (('runtime_bundle', 'parts', 0, 'url'), part['url'].replace('https://', 'http://')),
            (('runtime_bundle', 'parts', 0, 'url'), part['url'].replace('/Jeong-Luke/LAKIS/', '/Jeong-Luke/LAKIS_DEV/')),
            (('runtime_bundle', 'parts', 0, 'url'), part['url'] + '?download=1'),
            (('runtime_bundle', 'parts', 0, 'bytes'), 0),
            (('runtime_bundle', 'parts', 0, 'bytes'), -1),
            (('runtime_bundle', 'parts', 0, 'bytes'), 1024 ** 3 + 1),
            (('runtime_bundle', 'parts', 0, 'bytes'), 1.5),
            (('runtime_bundle', 'parts', 0, 'bytes'), str(part['bytes'])),
            (('runtime_bundle', 'parts', 0, 'bytes'), True),
            (('runtime_bundle', 'bytes'), manifest['runtime_bundle']['bytes'] + 1),
            (('runtime_bundle', 'bytes'), 0),
            (('runtime_bundle', 'files'), 0),
            (('runtime_bundle', 'url'), 'https://example.invalid/runtime.zip'),
        ))

    def test_reader_rejects_invalid_bootstrap_and_model_download_contracts(self):
        self.reject_manifest_cases((
            (('base', 'url'), 'http://example.invalid/bootstrap.7z'),
            (('base', 'name'), '../bootstrap.7z'),
            (('base', 'bytes'), 0),
            (('webview2', 'bytes'), '1844944'),
            (('models',), []),
            (('models', 0, 1), 'http://example.invalid/model'),
            (('models', 0, 4), 0),
            (('optional_animesharp',), []),
            (('optional_animesharp', 4), 0),
        ))

    def test_fresh_install_promotion_failure_and_target_conflict(self):
        self.run_probe(STAGING_PROBE)

    def test_repair_wrong_release_rejection_preserves_user_state_and_files(self):
        self.run_probe(REPAIR_PROBE)

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
            self.run_probe(FETCH_PROBE, [f'http://127.0.0.1:{server.server_port}/fixture'])
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
            self.run_probe(CONCURRENT_FETCH_PROBE, [f'http://127.0.0.1:{server.server_port}/fixture'])
            self.assertEqual(requests, ['/fixture'])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


@unittest.skipUnless(os.name == 'nt', 'Windows WebView2 registry validator required')
class ActivePythonWebViewVersionTests(unittest.TestCase):
    def test_active_installer_validates_registered_webview_versions(self):
        import winreg
        spec = importlib.util.spec_from_file_location('setup_probe_cmd_installer', ROOT/'installer/lakis_cmd_installer.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with mock.patch.object(winreg, 'OpenKey') as open_key, \
             mock.patch.object(winreg, 'QueryValueEx') as query:
            open_key.return_value.__enter__.return_value = 'fixture-key'
            for version in ('', '0.0.0.0', ' 0.0.0.0 ', 'not-a-version', '1.2', '1.2.3.-1', None):
                with self.subTest(version=version):
                    query.return_value = (version, winreg.REG_SZ)
                    self.assertFalse(installer.has_webview2_runtime())
            for version in ('160.0.4430.69', ' 160.0.4430.69 '):
                with self.subTest(version=version):
                    query.return_value = (version, winreg.REG_SZ)
                    self.assertTrue(installer.has_webview2_runtime())
            open_key.side_effect = OSError('registration missing')
            self.assertFalse(installer.has_webview2_runtime())


if __name__ == '__main__':
    unittest.main(verbosity=2)
