"""Exercise response-range and Windows write boundaries with real compiled code."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest import mock
import zipfile

import test_cmd_installer

module = test_cmd_installer.module
ROOT = Path(__file__).resolve().parents[2]
CSC = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
PROBE = r'''
using System;using System.IO;using System.Reflection;
class SecurityProbe {
 static object Call(Type type,string name,params object[] args){return type.GetMethod(name,BindingFlags.NonPublic|BindingFlags.Static).Invoke(null,args);}
 static int Main(string[] args){try{
  if(args[0]=="download"){Call(typeof(SafeInstaller),"Download",args[1],args[2],"fixture.bin",6L,(Action<string>)(_=>{}));return 0;}
  if(args[0]=="owned"){Call(typeof(UpdaterForm),"ValidateRelativePath",args[1]);return 0;}
  if(args[0]=="origin-ok"){Call(typeof(SafeInstaller),"ValidateDownloadOrigin",args[1],args[2]);Call(typeof(UpdaterForm),"ValidateDownloadOrigin",args[1],args[2]);return 0;}
  try {
   if(args[0]=="origin-reject"){Call(typeof(SafeInstaller),"ValidateDownloadOrigin",args[1],args[2]);return 10;}
   if(args[0]=="origin-reject-updater"){Call(typeof(UpdaterForm),"ValidateDownloadOrigin",args[1],args[2]);return 10;}
   if(args[0]=="zip")Call(typeof(SafeInstaller),"ExtractZip",args[1],args[2]);
   else if(args[0]=="copy")Call(typeof(SafeInstaller),"CopyTree",args[1],args[2]);
   else if(args[0]=="copy-lora")Call(typeof(SafeInstaller),"CopyLoraManagerForRepair",args[1],args[2]);
   else if(args[0]=="combine")Call(typeof(UpdaterForm),"SafeCombine",args[1],args[2]);
   else Call(typeof(UpdaterForm),args[0]=="delete"?"ValidateDeleteRelativePath":"ValidateRelativePath",args[1]);
   return 10;
  }catch(TargetInvocationException e){if(!(e.InnerException is IOException)&&!(e.InnerException is InvalidDataException))throw;Console.WriteLine("REJECTED");return 0;}
 }catch(Exception e){Console.Error.WriteLine(e);return 1;}}
}
'''


class CmdRangeTests(unittest.TestCase):
    def test_final_download_origin_rejects_downgrade_and_unapproved_hosts(self):
        requested='https://github.com/audit-fixture/archive'
        for final in ('http://github.com/archive','https://evil.invalid/archive',
                      'https://github.com.evil.invalid/archive','https://user:password@github.com/archive',
                      'http://127.0.0.1:9/archive','http://localhost:9/archive'):
            with self.subTest(final=final),self.assertRaises(module.InvalidDownloadOriginError):
                module.validate_download_origin(requested,final)
        module.validate_download_origin(requested,'https://codeload.github.com/archive')
        module.validate_download_origin('https://huggingface.co/archive','https://cas-bridge.xethub.hf.co/archive')
        module.validate_download_origin('http://127.0.0.1:19475/archive','http://127.0.0.1:19475/archive')
        with self.assertRaises(module.InvalidDownloadOriginError):
            module.validate_download_origin('http://127.0.0.1:19475/archive','http://127.0.0.1:9/archive')
    def test_invalid_range_is_rejected_before_body_and_restarts_fresh(self):
        for content_range in (None, 'bytes 0-2/6', 'bytes 3-5/7', 'bytes 3-4/6', 'bytes 3-5/*'):
            with self.subTest(header=content_range), tempfile.TemporaryDirectory() as directory:
                class Response(io.BytesIO):
                    def __init__(self, body, status, headers):
                        super().__init__(body); self.status=status; self.headers=headers; self.read_count=0
                    def read(self, size=-1):
                        self.read_count+=1; return super().read(size)
                headers={'Content-Length':'3'}
                if content_range is not None: headers['Content-Range']=content_range
                invalid=Response(b'def',206,headers)
                fresh=Response(b'abcdef',200,{'Content-Length':'6'})
                requests=[]; responses=iter((invalid,fresh))
                def open_response(request, timeout):
                    requests.append(request); return next(responses)
                target=Path(directory)/'model.bin';target.with_suffix('.bin.part').write_bytes(b'abc')
                with mock.patch.object(module.urllib.request,'urlopen',side_effect=open_response), mock.patch.object(module.time,'sleep'), mock.patch('sys.stdout',io.StringIO()):
                    module.download('https://github.com/audit-fixture/model',target,hashlib.sha256(b'abcdef').hexdigest().upper(),6)
                self.assertEqual(invalid.read_count,0)
                self.assertEqual(target.read_bytes(),b'abcdef')
                self.assertEqual(requests[0].get_header('Range'),'bytes=3-')
                self.assertIsNone(requests[1].get_header('Range'))


@unittest.skipUnless(CSC.is_file(),'Windows .NET compiler required')
class NativeWriteBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        probe=cls.root/'probe.cs';probe.write_text(PROBE,encoding='utf-8');cls.exe=cls.root/'probe.exe'
        command=[str(CSC),'/nologo','/target:exe','/main:SecurityProbe','/out:'+str(cls.exe),
                 '/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.Web.Extensions.dll',
                 '/r:System.IO.Compression.dll','/r:System.IO.Compression.FileSystem.dll',
                 str(ROOT/'installer/Setup_LAKIS_Safe.cs'),str(ROOT/'installer/LAKIS_Updater.cs'),
                 str(ROOT/'installer/SplashArtwork.cs'),str(probe)]
        result=subprocess.run(command,capture_output=True)
        if result.returncode:raise RuntimeError(result.stdout.decode(errors='replace'))
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def run_probe(self,*args):
        result=subprocess.run([str(self.exe),*map(str,args)],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        return result
    def test_actual_http_wrong_range_restarts_without_append(self):
        for header in (None,'bytes 0-2/6','bytes 3-5/7','bytes 3-4/6'):
            requests=[]
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*_):pass
                def do_GET(self):
                    value=self.headers.get('Range');requests.append(value)
                    body=b'def' if value else b'abcdef'
                    self.send_response(206 if value else 200)
                    self.send_header('Content-Length',str(len(body)))
                    if value and header:self.send_header('Content-Range',header)
                    self.end_headers();self.wfile.write(body)
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with self.subTest(header=header),tempfile.TemporaryDirectory(dir=self.root) as folder:
                    target=Path(folder)/'download.bin';partial=Path(str(target)+'.part');partial.write_bytes(b'abc')
                    self.run_probe('download',f'http://127.0.0.1:{server.server_port}/fixture',target)
                    self.assertEqual(partial.read_bytes(),b'abcdef');self.assertEqual(requests,['bytes=3-',None])
            finally:server.shutdown();server.server_close();thread.join(5)
    def test_native_final_origin_policy_matches_approved_providers(self):
        for requested,final in [('https://github.com/archive','https://release-assets.githubusercontent.com/archive'),
                                ('https://huggingface.co/archive','https://cas-bridge.xethub.hf.co/archive'),
                                ('http://127.0.0.1:19475/archive','http://127.0.0.1:19475/archive')]:
            self.run_probe('origin-ok',requested,final)
        for final in ('http://github.com/archive','https://evil.invalid/archive','https://github.com.evil.invalid/archive',
                      'http://127.0.0.1:9/archive','http://localhost:9/archive'):
            self.run_probe('origin-reject','https://github.com/archive',final)
            self.run_probe('origin-reject-updater','https://github.com/archive',final)
        self.run_probe('origin-reject','http://127.0.0.1:19475/archive','http://127.0.0.1:9/archive')
        self.run_probe('origin-reject-updater','http://127.0.0.1:19475/archive','http://127.0.0.1:9/archive')
    def test_updater_rejects_user_files_ads_devices_and_unknown_paths(self):
        for path in ('.lakis/settings.json','arbitrary-document.txt','app.js:payload',
                     'ComfyUI/LAKIS/external_ui/CON.txt','ComfyUI/LAKIS/external_ui/a.js:payload',
                     'ComfyUI/user/prompt.json','ComfyUI/models/loras/user.safetensors',
                     'ComfyUI/LAKIS/workflows/LAKIS_custom_v7.4_editable.json',
                     'ComfyUI/custom_nodes/ComfyUI-LAKIS-AutoPatch/startup_workflow.json',
                     'ComfyUI/LAKIS/external_ui/a.js.','ComfyUI/LAKIS/external_ui//a.js'):
            with self.subTest(path=path):self.run_probe('reject',path)
        self.run_probe('delete','LICENSE.md')
    def test_all_production_owned_source_paths_are_allowed(self):
        paths=['LAKIS.exe','Microsoft.Web.WebView2.Core.dll','ComfyUI/LAKIS/STOP_AUTOMATION',
               'ComfyUI/LAKIS/sync_runtime_workflow.py','ComfyUI/LAKIS/workflows/LAKIS_runtime_api_v7.4.json',
               'ComfyUI/LAKIS/workflows/LAKIS_runtime_visual_v7.4.json']
        for path in (ROOT/'src/external_ui').rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':paths.append('ComfyUI/LAKIS/external_ui/'+path.relative_to(ROOT/'src/external_ui').as_posix())
        for name in (ROOT/'resources/PRODUCTION_NODE_PACKAGES.txt').read_text().splitlines():
            if name and not name.startswith('#'):paths.append('ComfyUI/custom_nodes/'+name+'/__init__.py')
        for path in paths:self.run_probe('owned',path)
    def test_existing_junction_is_rejected_before_zip_or_update_write(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            root=Path(folder);stage=root/'stage';sibling=root/'sibling';stage.mkdir();sibling.mkdir()
            link=stage/'linked'
            # Quote the bounded, generated tempfile paths as PowerShell literals.
            script="New-Item -ItemType Junction -Path '"+str(link).replace("'","''")+"' -Target '"+str(sibling).replace("'","''")+"' | Out-Null"
            result=subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            try:
                archive=root/'test.zip'
                with zipfile.ZipFile(archive,'w') as z:z.writestr('linked/audit-owned.txt',b'must not escape')
                self.run_probe('zip',archive,stage);self.run_probe('combine',stage,'linked/audit-owned.txt')
                source=root/'source';(source/'linked').mkdir(parents=True)
                (source/'linked/audit-owned.txt').write_bytes(b'must not escape')
                self.run_probe('copy',source,stage);self.run_probe('copy-lora',source,stage)
                self.assertEqual(list(sibling.iterdir()),[])
            finally:
                # Remove the link itself, not its target, before ordinary temp cleanup.
                os.rmdir(link)
