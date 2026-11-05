"""Static source/package contract checks, NOT Windows installer execution."""
import ast
import base64
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(os.environ.get('LAKIS_TEST_SOURCE_ROOT') or Path(__file__).resolve().parents[2])
class ReleaseSourceContracts(unittest.TestCase):
    def text(self,path):return (ROOT/path).read_text(encoding='utf-8-sig')
    def names(self):return [s.strip() for s in self.text('resources/PRODUCTION_NODE_PACKAGES.txt').splitlines() if s.strip() and not s.startswith('#')]
    def test_public_launcher_runtime_is_not_dev(self):
        s=self.text('installer/LAKIS_Launcher.cs')
        self.assertIn('(DevelopmentBuild ? "LAKIS_DEV" : "LAKIS")',s)
    def test_update_check_precedes_runtime_missing_error(self):
        s=self.text('installer/LAKIS_Launcher.cs')
        self.assertLess(s.index('TryGetLatestVersion(out latest'),s.index('if (!File.Exists(python) || !File.Exists(launcher))'))
    def test_setup_and_repair_only_install_public_ui(self):
        s=self.text('installer/Setup_LAKIS_Safe.cs')
        self.assertNotIn('Path.Combine(comfy,"LAKIS_DEV"',s)
        install=s[s.index('internal static void Install('):s.index('private static InvalidOperationException RuntimeFailure')]
        repair=s[s.index('internal static void Repair'):s.index('private static string Fetch')]
        for entry in (install,repair):
            self.assertIn('string manifest=ReadRuntimeInstallManifest();',entry)
        self.assertIn('RunRuntimeInstaller(manifest,target,cache,"fresh",includeAnimeSharp,status)',install)
        self.assertIn('RunRuntimeInstaller(manifest,target,cache,"repair",false,status)',repair)
        self.assertIn('RuntimeBundleInstaller.Install(python,manifest,target,cache,mode,includeAnimeSharp,status)',s)
        manifest=self.text('installer/runtime_manifest.py')
        required=next(ast.literal_eval(node.value) for node in ast.parse(manifest).body
                      if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REQUIRED_FILES' for t in node.targets))
        for name in ('LAKIS_Model_Importer.exe','THIRD_PARTY_NOTICES.md','ComfyUI/LAKIS/STOP_AUTOMATION'):
            self.assertIn(name,required)
        self.assertFalse(any(re.search(r'LAKIS_DEV|LAKIS_LUKE|Light-Control|DSINE',name) for name in required))
    def test_runtime_supply_helpers_are_shared(self):
        s=self.text('installer/Setup_LAKIS_Safe.cs');g=self.text('installer/New-UpdateManifest.ps1')
        bridge=self.text('installer/RuntimeBundleInstaller.cs')
        runtime=self.text('installer/runtime_install.py')
        self.assertIn('runtime_install.py',bridge)
        self.assertIn('"--mode", mode, "--method", "gui"',bridge)
        self.assertIn('return activate(candidate, target, bundle["manifest_sha256"], version, mode,',runtime)
        self.assertIn('PRODUCTION_NODE_PACKAGES.txt',g)
        self.assertIn('ComfyUI/LAKIS/sync_runtime_workflow.py',g)
        workflow_names=(
            'LAKIS_runtime_api_v7.4.json',
            'LAKIS_runtime_visual_v7.4.json',
            'LAKIS_custom_v7.4_editable.json',
        )
        for name in workflow_names:
            workflow=(ROOT/'workflows'/name).read_bytes()
            self.assertIn(b'RealESRGAN_x4plus_anime_6B.pth',workflow,name)
            self.assertNotIn(b'2x-AnimeSharpV4_Fast_RCAN_PU.safetensors',workflow,name)
            self.assertIn('ComfyUI/LAKIS/workflows/'+workflow_names[0],self.text('installer/runtime_manifest.py'))
            if not name.endswith('_editable.json'):
                self.assertIn(name,g)
        # Update, Fresh Setup, and Repair must copy the same canonical bytes.
        # Optional user choices are persisted separately and resolved at runtime.
        self.assertNotIn('SetDefaultUpscaler(',s)
        self.assertNotIn('Directory.GetFiles(root,"*.json"',s)
        repair=s[s.index('internal static void Repair'):s.index('private static string Fetch')]
        self.assertNotIn('Path.Combine(comfy,"user"',repair)
        self.assertNotIn('LAKIS_custom_v7.4_editable.json',repair)
        self.assertNotIn('Add-UpdateFile "ComfyUI/user',g)
        update_workflows=g[g.index('foreach ($runtimeName'):g.index('$retiredFiles')]
        self.assertNotIn('LAKIS_custom_v7.4_editable.json',update_workflows)
        retired=g[g.index('$retiredFiles'):g.index('$filePaths')]
        self.assertNotIn('LAKIS_custom_v7.3_editable.json',retired)
    def test_setup_and_repair_verify_trusted_runtime_manifest(self):
        s=self.text('installer/Setup_LAKIS_Safe.cs')
        self.assertIn('GetManifestResourceStream("LAKIS.RuntimeInstallManifest")',s)
        self.assertIn('RequiredString(manifest,"version"),ReleaseVersion,StringComparison.Ordinal',s)
        self.assertIn('ValidateRuntimeBundle(RequiredObject(manifest,"runtime_bundle"))',s)
        manifest=self.text('installer/runtime_manifest.py')
        self.assertIn('hashlib.sha256(raw_manifest).hexdigest().upper() != expected_hash.upper()',manifest)
        self.assertIn('(root / "VERSION").read_text(encoding="utf-8-sig").strip() != expected_version',manifest)
        transition=self.text('installer/runtime_transition.py')
        self.assertIn('verify_runtime(target, manifest_sha256, version, allow_user_data=True)',transition)
    def test_setup_uses_official_webview_product_registration(self):
        s=self.text('installer/lakis_cmd_installer.py')
        self.assertIn('{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',s)
        self.assertIn("winreg.QueryValueEx(key, 'pv')",s)
        self.assertNotIn('name.IndexOf("WebView2"',s)
        self.assertIn('ensure_webview2_runtime(manifest, cache)',self.text('installer/runtime_install.py'))
    def test_every_managed_provider_has_source_and_no_retired_package(self):
        names=self.names();self.assertEqual(len(names),len(set(n.casefold() for n in names)))
        for n in names:
            self.assertRegex(n,r'^[A-Za-z0-9_-]+$')
            self.assertTrue((ROOT/'src/custom_nodes'/n/'__init__.py').is_file(),n)
            self.assertNotIn('Light-Control',n);self.assertNotIn('Pose',n)
        self.assertTrue({'ComfyUI-LAKIS-Detail','ComfyUI-LAKIS-Fast-Refiner','ComfyUI-LAKIS-AutoPatch'}<=set(names))
    def test_provider_licenses_preserved_and_dev_loader_removed(self):
        for n in ('ComfyUI-LAKIS-Detail','ComfyUI-LAKIS-Fast-Refiner'):
            self.assertTrue((ROOT/'src/custom_nodes'/n/'LICENSE').is_file())
            self.assertTrue((ROOT/'src/custom_nodes'/n/'NOTICE.md').is_file())
        self.assertNotIn('C:\\AI Library',self.text('src/custom_nodes/ComfyUI-LAKIS-Detail/__init__.py'))
    def test_no_bulk_process_termination_in_setup_or_updater(self):
        setup=self.text('installer/Setup_LAKIS_Safe.cs');updater=self.text('installer/LAKIS_Updater.cs')
        part=setup[setup.index('private static void StopOwned'):]
        part+=updater[updater.index('private void StopInstalledProcesses'):updater.index('private void SetStatus')]
        self.assertNotIn('.Kill()',part);self.assertIn('throw new IOException',part)
    def test_successful_splash_close_does_not_kill_children(self):
        s=self.text('installer/LAKIS_Launcher.cs')
        self.assertIn('if (!startupCompleted) StopStartupProcessTree()',s)
        self.assertIn('startupCompleted = true;',s);self.assertIn('process.StartTime != startupProcessStartedAt',s)
        self.assertNotIn('/IM python',s)
    def test_updater_alias_self_update_is_validated(self):
        s=self.text('installer/LAKIS_Updater.cs');self.assertIn('--self-name=',s)
        self.assertIn('Path.Combine(root, selfName)',s);self.assertIn('Invalid updater self-update target.',s)
        finish=s[s.index('private static void FinishSelfUpdate'):]
        self.assertIn('oldProcess.MainModule.FileName',finish)
        self.assertIn('Legacy updater process is not an approved executable in the installation root.',finish)
        self.assertLess(finish.index('oldProcess.MainModule.FileName'),finish.index('oldProcess.WaitForExit(1000)'))
        self.assertIn('Updater process identity does not match the approved self-update target.',finish)
        self.assertIn('ComputeSha256(Application.ExecutablePath)',finish)
        self.assertIn('patcherIsCandidate == updaterIsCandidate',finish)
        self.assertIn('Legacy updater alias cannot be determined safely from installation state.',finish)
        self.assertIn('selfName = patcherIsCandidate ? "LAKIS_Updater.exe" : "LAKIS_Patcher.exe";',finish)
        self.assertIn('if (!oldProcess.WaitForExit(1000))',finish)
        self.assertIn('oldProcess.Kill();',finish)
        self.assertIn('oldProcess.WaitForExit(5000)',finish)
        self.assertIn('self-update-retired',finish)
        self.assertIn('File.Move(destination, retiredExecutable);',finish)
        self.assertLess(finish.index('File.Move(destination, retiredExecutable);'),finish.index('oldProcess.WaitForExit(1000)'))
        self.assertLess(finish.index('File.Copy(Application.ExecutablePath, destination, true)'),finish.index('oldProcess.Kill();'))
        self.assertLess(finish.index('File.WriteAllText(Path.Combine(root, "VERSION"), version)'),finish.index('oldProcess.Kill();'))
        self.assertIn('File.Move(retiredExecutable, destination);',finish)
        self.assertIn('Path.Combine(root, "LAKIS_Patcher.exe")',finish)
        self.assertIn('Path.Combine(root, "LAKIS_Updater.exe")',finish)
    def test_build_source_pinned_and_not_parent_workspace(self):
        s=self.text('installer/build_safe_installer.ps1')
        self.assertIn('INSTALLER_SOURCE_REVISION',s);self.assertIn('working tree is dirty',s)
        self.assertIn('$pinnedSetupSource',s);self.assertIn('$workspace = $repo',s)
        self.assertIn('$workspace = $repo',self.text('installer/New-UpdateManifest.ps1'))
    def test_monitor_api_policy_preserved(self):
        s=self.text('src/external_ui/serve_ui.py')
        self.assertIn('PREFERRED_LAKIS_WORKFLOW = PACKAGED_WORKFLOW_ROOT / "LAKIS_runtime_api_v8.0.json"',s)
        self.assertIn('RUNTIME_LAKIS_WORKFLOW = PREFERRED_LAKIS_WORKFLOW',s)
    def test_error_codes_documented(self):
        s=self.text('ERROR_CODES.md');self.assertIn('LKS-GEN-1011',s);self.assertIn('LKS-GEN-1012',s)
@unittest.skipUnless(os.name == 'nt', 'PowerShell release contract requires Windows')
class RuntimeInstallerGateTests(unittest.TestCase):
    """Execute only the installer gate, never the full release gate or Setup."""
    files = (
        'installer/Setup_LAKIS_Safe.cs', 'installer/LAKIS_Uninstaller.cs',
        'installer/RuntimeBundleInstaller.cs', 'installer/runtime_install.py',
        'installer/runtime_manifest.py', 'installer/runtime_transition.py',
        'installer/cmd-installer-manifest.json',
    )

    def run_gate(self, root):
        quote=lambda path: str(path).replace("'", "''")
        version=(ROOT/'VERSION').read_text(encoding='utf-8-sig').strip()
        command = """
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('%s', [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw $errors[0] }
foreach ($name in @('Require', 'Read-RepoFile', 'Test-RuntimeInstallerContract')) {
    $node = $ast.Find({param($entry) $entry -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $entry.Name -eq $name}, $true)
    . ([scriptblock]::Create($node.Extent.Text))
}
$repo = '%s'
Test-RuntimeInstallerContract '%s'
""" % (quote(ROOT/'installer/Test-ReleaseRegression.ps1'), quote(root), version)
        encoded=base64.b64encode(command.encode('utf-16-le')).decode('ascii')
        powershell=Path(os.environ['WINDIR'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        return subprocess.run([str(powershell),'-NoProfile','-EncodedCommand',encoded],
                              capture_output=True,timeout=30)

    def test_active_runtime_contract_passes_without_legacy_setup_literals(self):
        result=self.run_gate(ROOT)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))

    def test_gate_rejects_missing_active_contracts(self):
        mutations=(
            ('installer/runtime_manifest.py', '"LAKIS_Model_Importer.exe", ', '', 'REQUIRED_FILES'),
            ('installer/runtime_manifest.py', '.strip() != expected_version', '.strip() == expected_version', 'Installed VERSION'),
            ('installer/Setup_LAKIS_Safe.cs', 'RuntimeBundleInstaller.Install(python,manifest,target,cache,mode,includeAnimeSharp,status);', 'throw new InvalidOperationException();', 'Runtime Setup invariant'),
            ('installer/runtime_install.py', 'return activate(candidate, target, bundle["manifest_sha256"], version, mode,', 'return replaced_engine(candidate, target, bundle["manifest_sha256"], version, mode,', 'Runtime installation invariant'),
            ('installer/Setup_LAKIS_Safe.cs', 'if(HasDirectoryEntries(target))', 'if(false)', 'non-empty destination'),
            ('installer/Setup_LAKIS_Safe.cs', 'if(IsExistingInstallation(target))', 'if(false)', 'existing LAKIS installation'),
            ('installer/runtime_transition.py', '_copy_data(data_source, stage)', 'pass', 'data-protection'),
            ('installer/cmd-installer-manifest.json', 'D6D8BC920C7A74BE4728C0F7703744469E62E80502F297E582EE1A1406FA052D', '0'*64, 'source hash'),
            ('installer/cmd-installer-manifest.json', '457fbf842cb86e96af72c65bdd13e3f1c448de84', '0'*40, 'model URL/hash'),
        )
        for path,old,new,message in mutations:
            with self.subTest(path=path,contract=message),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                for relative in self.files:
                    target=root/relative
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(ROOT/relative,target)
                target=root/path
                text=target.read_text(encoding='utf-8-sig')
                self.assertIn(old,text)
                target.write_text(text.replace(old,new),encoding='utf-8')
                result=self.run_gate(root)
                self.assertNotEqual(result.returncode,0)
                self.assertIn(message,result.stderr.decode(errors='replace'))

if __name__=='__main__':unittest.main(verbosity=2)
