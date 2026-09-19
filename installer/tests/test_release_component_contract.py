"""Static source/package contract checks, NOT Windows installer execution."""
import ast
import os
from pathlib import Path
import re
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
        repair=s[s.index('internal static void Repair'):s.index('private static string Fetch')]
        self.assertIn('"STOP_AUTOMATION"',repair);self.assertIn('CopyManagedNodePackages(uiRoot, custom)',repair)
    def test_runtime_supply_helpers_are_shared(self):
        s=self.text('installer/Setup_LAKIS_Safe.cs');g=self.text('installer/New-UpdateManifest.ps1')
        self.assertIn('CopyManagedNodePackages(lakis, custom)',s)
        self.assertIn('PRODUCTION_NODE_PACKAGES.txt',s);self.assertIn('PRODUCTION_NODE_PACKAGES.txt',g)
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
            self.assertIn(name,s)
            self.assertIn(name,g)
        # Update, Fresh Setup, and Repair must copy the same canonical bytes.
        # Optional user choices are persisted separately and resolved at runtime.
        self.assertNotIn('SetDefaultUpscaler(',s)
        self.assertNotIn('Directory.GetFiles(root,"*.json"',s)
        repair=s[s.index('internal static void Repair'):s.index('private static string Fetch')]
        self.assertNotIn('Path.Combine(comfy,"user"',repair)
        self.assertNotIn('Add-UpdateFile "ComfyUI/user',g)
    def test_setup_and_repair_verify_cached_source_archive(self):
        s=self.text('installer/Setup_LAKIS_Safe.cs')
        install=s[s.index('internal static void Install'):s.index('internal static void Repair')]
        repair=s[s.index('internal static void Repair'):s.index('private static string Fetch')]
        self.assertIn('string lakisZip=Fetch(lakisItem,cache,status);',install)
        self.assertIn('string uiZip=Fetch(uiItem,cache,status);',repair)
        self.assertNotIn('if(!File.Exists(lakisZip))',install)
        self.assertNotIn('if(!File.Exists(uiZip))',repair)
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
        self.assertIn('RUNTIME_LAKIS_WORKFLOW = PACKAGED_WORKFLOW_ROOT / "LAKIS_runtime_api_v7.4.json"',s)
    def test_error_codes_documented(self):
        s=self.text('ERROR_CODES.md');self.assertIn('LKS-GEN-1011',s);self.assertIn('LKS-GEN-1012',s)
if __name__=='__main__':unittest.main(verbosity=2)
