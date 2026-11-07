"""Compile the preview Setup upgrade entry without touching real installations."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "installer"))
import runtime_manifest
CSC = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
PROBE = r'''
using System;
using System.IO;
using System.Net;
using System.Reflection;
internal static class PreviewUpgradeProbe {
    private static int Main(string[] args) {
        try {
            if(args[0]=="mode") {
                Console.WriteLine(SafeInstaller.ExistingInstallationMode(args[1]));
            } else if(args[0]=="recover") {
                RuntimeBundleInstaller.Recover(args[2],args[1],Console.WriteLine);
            } else if(args[0]=="fresh") {
                var validate=typeof(SafeInstaller).GetMethod("ValidateFreshTarget",BindingFlags.NonPublic|BindingFlags.Static);
                validate.Invoke(null,new object[]{args[1]});
            } else if(args[0]=="repair") {
                SafeInstaller.Repair(args[1],Console.WriteLine);
            } else if(args[0]=="manifest") {
                Console.WriteLine(RuntimeBundleInstaller.CreateUpdateManifest(File.ReadAllText(args[1])));
            } else if(args[0]=="inside") {
                RuntimeBundleInstaller.Install("not-run", "{}", args[1], args[1], "update", false, _=>{});
                return 20;
            } else if(args[0]=="headless") {
                var main=typeof(SafeSetupForm).GetMethod("Main",BindingFlags.NonPublic|BindingFlags.Static);
                return (int)main.Invoke(null,new object[]{new[]{"--headless","--install-dir",args[1],"--update","--repair"}});
            } else if(args[0]=="same") {
                SafeInstaller.Update(args[1],_=>{});
                return 21;
            } else if(args[0]=="engine") {
                RuntimeBundleInstaller.VerifyCandidateEngine(args[1]);
                RuntimeBundleInstaller.VerifyCandidateEngine(args[1]);
            } else if(args[0]=="engine-change") {
                RuntimeBundleInstaller.VerifyCandidateEngine(args[1]);
                foreach(string name in new[]{"LAKIS.exe","LAKIS_Updater.exe","LAKIS_Patcher.exe"})
                    File.Copy(Path.Combine(args[1],"older",name),Path.Combine(args[1],name),true);
                RuntimeBundleInstaller.VerifyCandidateEngine(args[1]);
            } else if(args[0]=="update-entry") {
                WebRequest.DefaultWebProxy=new WebProxy("http://127.0.0.1:1");
                var run=typeof(SafeInstaller).GetMethod("RunRuntimeInstaller",BindingFlags.NonPublic|BindingFlags.Static);
                try {
                    run.Invoke(null,new object[]{"{}",args[1],Path.Combine(args[1],"cache"),"update",false,(Action<string>)(_=>{})});
                    return 23;
                } catch(TargetInvocationException error) {
                    if(error.InnerException is InvalidDataException) {
                        Console.WriteLine("INSTALLED_PYTHON_READY_FOR_MANIFEST");
                        return 0;
                    }
                    throw;
                }
            } else return 22;
            return 0;
        } catch(Exception error) {
            Console.Error.WriteLine(error.ToString());
            return 1;
        }
    }
}
'''


@unittest.skipUnless(CSC.is_file(), "Windows .NET Framework compiler required")
class PreviewUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="lakis-preview-upgrade-")
        cls.root = Path(cls.temp.name)
        probe = cls.root / "probe.cs"
        probe.write_text(PROBE, encoding="utf-8")
        cls.exe = cls.root / "probe.exe"
        command = [
            str(CSC), "/nologo", "/target:exe", "/main:PreviewUpgradeProbe",
            "/out:" + str(cls.exe),
            *["/reference:" + name for name in (
                "System.Windows.Forms.dll", "System.Drawing.dll",
                "System.Web.Extensions.dll", "System.IO.Compression.dll",
                "System.IO.Compression.FileSystem.dll")],
            *[str(ROOT / "installer" / name) for name in (
                "SplashArtwork.cs", "UpdateProtocol.cs",
                "RuntimeBundleInstaller.cs", "Setup_LAKIS_Safe.cs")],
            *["/resource:" + str(ROOT / "installer" / name) + ",LAKIS.Runtime." + name
              for name in ("lakis_cmd_installer.py", "runtime_install.py", "runtime_transition.py",
                           "runtime_manifest.py", "runtime_health.py", "runtime_patch.py", "runtime_update.py")],
            str(probe),
        ]
        cls.compile_command = command
        result = subprocess.run(command, capture_output=True, timeout=60)
        if result.returncode:
            cls.temp.cleanup()
            raise RuntimeError(result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_probe(self, action, path):
        return subprocess.run([str(self.exe), action, str(path)],
                              capture_output=True, timeout=15)

    def installation(self, root, version):
        (root / "ComfyUI/LAKIS").mkdir(parents=True)
        (root / "ComfyUI/LAKIS/STOP_AUTOMATION").write_bytes(b"keep")
        (root / "VERSION").write_text(version, encoding="ascii")
        (root / "owner.txt").write_bytes(b"existing user data")

    def test_existing_versions_select_update_or_repair_without_writes(self):
        for version, expected in (("8.0.0", "update"), ("8.0.2", "update"),
                                  ("8.0.3", "update"), ("8.1.0", "repair")):
            with self.subTest(version=version), tempfile.TemporaryDirectory(dir=self.root) as folder:
                root = Path(folder)
                self.installation(root, version)
                before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                result = self.run_probe("mode", root)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                self.assertEqual(result.stdout.decode().strip(), expected)
                self.assertEqual({p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}, before)

    def test_newer_legacy_and_malformed_versions_are_not_upgraded(self):
        for version in ("8.2.0", "7.5.4", "invalid", "8.1"):
            with self.subTest(version=version), tempfile.TemporaryDirectory(dir=self.root) as folder:
                root = Path(folder)
                self.installation(root, version)
                self.assertNotEqual(self.run_probe("mode", root).returncode, 0)
                self.assertEqual((root / "VERSION").read_text(), version)
                self.assertEqual((root / "owner.txt").read_bytes(), b"existing user data")

    def test_empty_folder_is_not_an_existing_installation(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            root = Path(folder)
            self.assertNotEqual(self.run_probe("mode", root).returncode, 0)
            self.assertEqual(list(root.iterdir()), [])

    def interrupted_installation(self, parent, phase="staged"):
        target = parent / "installed"
        self.installation(target, "8.1.1")
        (target / "LAKIS.exe").write_bytes(b"original launcher")
        workspace = parent / ".installed-recovery-test"
        workspace.mkdir()
        state = {
            "schema": 1, "target": str(target), "version": "8.1.0",
            "manifest_sha256": "A" * 64, "had_original": True,
            "workspace": workspace.name, "phase": phase,
        }
        journal = parent / ".installed-runtime-transition.json"
        journal.write_text(json.dumps(state), encoding="utf-8")
        return target, workspace, state, journal

    def test_interrupted_update_enables_recovery_even_for_newer_or_missing_installation(self):
        for missing in (False, True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory(dir=self.root) as folder:
                target, workspace, state, journal = self.interrupted_installation(Path(folder))
                if missing:
                    target.rename(workspace / "backup")
                before = journal.read_bytes()
                result = self.run_probe("mode", target)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                self.assertEqual(result.stdout.decode().strip(), "recover")
                self.assertEqual(journal.read_bytes(), before)
                self.assertFalse((workspace / "failed").exists())

    def test_fresh_install_cannot_bypass_an_interrupted_update_with_missing_target(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            target, workspace, state, journal = self.interrupted_installation(Path(folder))
            target.rename(workspace / "backup")
            result = self.run_probe("fresh", target)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(target.exists())
            self.assertEqual((workspace / "backup/VERSION").read_text(), "8.1.1")
            self.assertEqual(json.loads(journal.read_text()), state)

    def test_finished_transition_does_not_allow_a_newer_installation_to_be_downgraded(self):
        for phase in ("complete", "rolled-back"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory(dir=self.root) as folder:
                target, workspace, state, journal = self.interrupted_installation(Path(folder), phase)
                before = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
                self.assertEqual(self.run_probe("repair", target).returncode, 1)
                self.assertEqual({p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}, before)
                self.assertEqual(json.loads(journal.read_text()), state)

    def test_recovery_restores_interrupted_promotion_and_preserves_both_trees(self):
        for promoted in (False, True):
            with self.subTest(promoted=promoted), tempfile.TemporaryDirectory(dir=self.root) as folder:
                parent = Path(folder)
                target, workspace, state, journal = self.interrupted_installation(parent, "promoting")
                (target / "ComfyUI/output").mkdir()
                (target / "ComfyUI/output/user.png").write_bytes(b"original user image")
                original = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
                target.rename(workspace / "backup")
                failed = {"partial.bin": b"retained incomplete update"}
                if promoted:
                    target.mkdir()
                    raw = b"candidate manifest marker"
                    state["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
                    (target / runtime_manifest.MANIFEST_NAME).write_bytes(raw)
                    for name, content in failed.items():
                        (target / name).write_bytes(content)
                    journal.write_text(json.dumps(state), encoding="utf-8")
                else:
                    (workspace / "stage").mkdir()
                    (workspace / "stage/partial.bin").write_bytes(failed["partial.bin"])
                result = subprocess.run([str(self.exe), "recover", str(target), sys.executable],
                                        capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                self.assertEqual({p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}, original)
                retained = workspace / ("failed" if promoted else "stage")
                self.assertEqual((retained / "partial.bin").read_bytes(), failed["partial.bin"])
                self.assertEqual(json.loads(journal.read_text())["phase"], "rolled-back")
                self.assertEqual((target / "VERSION").read_text(), "8.1.1")

    def test_recovery_rejects_mismatched_journal_without_touching_original_data(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            target, workspace, state, journal = self.interrupted_installation(Path(folder))
            state["target"] = str(Path(folder) / "unrelated")
            journal.write_text(json.dumps(state), encoding="utf-8")
            original = (target / "owner.txt").read_bytes()
            self.assertEqual(self.run_probe("mode", target).returncode, 1)
            result = subprocess.run([str(self.exe), "recover", str(target), sys.executable],
                                    capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 1)
            self.assertEqual((target / "owner.txt").read_bytes(), original)
            self.assertEqual(json.loads(journal.read_text()), state)

    def test_missing_backup_blocks_recovery_without_clearing_the_journal(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            target, workspace, state, journal = self.interrupted_installation(Path(folder), "promoting")
            target.rename(workspace / "retained-original")
            result = subprocess.run([str(self.exe), "recover", str(target), sys.executable],
                                    capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(target.exists())
            self.assertEqual((workspace / "retained-original/owner.txt").read_bytes(), b"existing user data")
            self.assertEqual(json.loads(journal.read_text()), state)

    def test_locked_installation_is_not_partially_restored(self):
        import ctypes
        from ctypes import wintypes
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            target, workspace, state, journal = self.interrupted_installation(Path(folder))
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = create(str(target / "owner.txt"), 0x80000000, 0, None, 3, 0x80, None)
            self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
            try:
                result = subprocess.run([str(self.exe), "recover", str(target), sys.executable],
                                        capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(journal.read_text()), state)
                self.assertFalse((workspace / "backup").exists())
            finally:
                kernel.CloseHandle(handle)
            self.assertEqual((target / "owner.txt").read_bytes(), b"existing user data")

    def test_update_uses_installed_python_without_downloading_bootstrap(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            root = Path(folder)
            self.installation(root, "8.0.0")
            python = root / "python_embeded/python.exe"
            python.parent.mkdir()
            python.write_bytes(b"not executed: manifest validation must happen first")
            result = self.run_probe("update-entry", root)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            self.assertIn(b"INSTALLED_PYTHON_READY_FOR_MANIFEST", result.stdout)
            self.assertFalse((root / "cache").exists())
            self.assertEqual((root / "VERSION").read_text(), "8.0.0")

    def test_missing_installed_python_requires_repair_without_network_or_writes(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            root = Path(folder)
            self.installation(root, "8.0.0")
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            result = self.run_probe("update-entry", root)
            self.assertEqual(result.returncode, 1)
            self.assertIn(b"FileNotFoundException", result.stderr)
            self.assertEqual({p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}, before)

    def test_same_version_update_rejected_before_manifest_or_network_access(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            root = Path(folder)
            self.installation(root, "8.1.0")
            result = self.run_probe("same", root)
            self.assertEqual(result.returncode, 1)
            self.assertIn(b"InvalidOperationException", result.stderr)
            self.assertEqual((root / "VERSION").read_text(), "8.1.0")

    def test_setup_inside_destination_cannot_replace_its_own_components(self):
        result = self.run_probe("inside", self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"InvalidOperationException", result.stderr)

    def test_conflicting_headless_modes_rejected(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            self.assertEqual(self.run_probe("headless", Path(folder)).returncode, 2)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def compile_candidate(self, root, older=False):
        root.mkdir(exist_ok=True)
        for name in ("LAKIS.exe", "LAKIS_Updater.exe"):
            command = ["/out:" + str(root / name) if arg.startswith("/out:") else arg
                       for arg in self.compile_command]
            if older:
                command.append("/define:LAKIS_RUNTIME_BRIDGE")
            result = subprocess.run(command, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace"))
        shutil.copyfile(root / "LAKIS_Updater.exe", root / "LAKIS_Patcher.exe")

    def test_candidate_engine_can_be_verified_at_prepare_and_apply_in_one_setup_process(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            root = Path(folder)
            self.compile_candidate(root)
            result = self.run_probe("engine", root)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_recheck_rejects_replaced_candidate_instead_of_using_cached_metadata(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            root = Path(folder)
            self.compile_candidate(root)
            self.compile_candidate(root / "older", older=True)
            result = self.run_probe("engine-change", root)
            self.assertEqual(result.returncode, 1)
            self.assertIn(b"Candidate updater capability regressed", result.stderr)

    def test_pinned_installer_bundle_becomes_model_capable_update(self):
        bundle = {
            "schema": 2, "product": "LAKIS", "version": "8.1.0",
            "manifest_sha256": "A" * 64,
            "assets": [{"url": "https://github.com/Jeong-Luke/LAKIS/releases/download/v8.1.0/runtime.zip",
                        "size": 123, "sha256": "B" * 64}],
        }
        source = {"schema": 1, "version": "8.1.0", "runtime_bundle": bundle,
                  "models": [["must not become a program file"]]}
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            manifest = Path(folder) / "installer.json"
            original = json.dumps(source).encode()
            manifest.write_bytes(original)
            result = self.run_probe("manifest", manifest)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            update = json.loads(result.stdout)
            self.assertEqual(update["kind"], "runtime-update")
            self.assertEqual(update["version"], "8.1.0")
            self.assertEqual(update["minimum_version"], "8.0.0")
            self.assertEqual(update["minimum_updater_version"], "8.1.0")
            self.assertEqual(update["runtime_bundle"], bundle)
            self.assertEqual(update["files"], [])
            self.assertEqual(update["delete"], [])
            self.assertEqual(manifest.read_bytes(), original)

    def test_bad_source_or_runtime_identity_never_becomes_update(self):
        variants = [
            {},
            {"schema": 2, "version": "8.1.0", "runtime_bundle": {}},
            {"schema": 1, "version": "8.0.3", "runtime_bundle": {}},
            {"schema": 1, "version": "8.1.0", "runtime_bundle": {
                "schema": 2, "product": "LAKIS", "version": "8.0.3",
                "manifest_sha256": "A" * 64}},
        ]
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            manifest = Path(folder) / "installer.json"
            for value in variants:
                with self.subTest(value=value):
                    manifest.write_text(json.dumps(value))
                    self.assertNotEqual(self.run_probe("manifest", manifest).returncode, 0)


if __name__ == "__main__":
    unittest.main()
