import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "installer"
LAYOUT_SCRIPT = INSTALLER / "New-ReleaseLayout.ps1"
CSC = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"

ROOT_ASSETS = (
    "LAKIS.exe",
    "LAKIS_Patcher.exe",
    "LAKIS_Updater.exe",
    "LAKIS_Desktop.exe",
    "LAKIS_Model_Importer.exe",
    "Uninstall_LAKIS.exe",
    "Microsoft.Web.WebView2.Core.dll",
    "Microsoft.Web.WebView2.WinForms.dll",
    "WebView2Loader.dll",
)

REPAIR_ATTEMPT_PROBE = r'''
using System;
using System.IO;
using System.Reflection;
internal static class RepairAttemptProbe {
    private static bool HasAttempt(string marker, string version) {
        var startup = typeof(LakisLauncher).GetNestedType("StartupForm", BindingFlags.NonPublic);
        var method = startup.GetMethod(
            "HasAutomaticRepairAttempt", BindingFlags.NonPublic | BindingFlags.Static);
        return (bool)method.Invoke(null, new object[] { marker, version });
    }
    private static int Main(string[] args) {
        bool result;
        if (args[0] == "locked") {
            using (var marker = new FileStream(args[1], FileMode.Open, FileAccess.Read, FileShare.None))
                result = HasAttempt(args[1], args[2]);
        } else {
            result = HasAttempt(args[1], args[2]);
        }
        Console.WriteLine(result ? "true" : "false");
        return 0;
    }
}
'''


class ReleaseLayoutTests(unittest.TestCase):
    def build_fixture(self, directory: Path):
        dist = directory / "dist"
        dist.mkdir()
        for index, name in enumerate(ROOT_ASSETS):
            (dist / name).write_bytes((name + f"-{index}").encode("utf-8"))
        layout = dist / "release-layout.json"
        pack = dist / "LAKIS_RepairPack.zip"
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(LAYOUT_SCRIPT),
                "-DistDirectory",
                str(dist),
                "-OutputPath",
                str(layout),
                "-RepairPackPath",
                str(pack),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(layout.is_file())
        self.assertTrue(pack.is_file())
        return json.loads(layout.read_text(encoding="utf-8-sig")), pack

    def test_layout_and_repair_pack_are_same_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            payload, pack = self.build_fixture(Path(directory))
            self.assertEqual(1, payload["schema"])
            self.assertEqual("LAKIS", payload["product"])
            self.assertEqual("preserve-v1", payload["editable_template_policy"])
            self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), payload["version"])

            files = {item["path"]: item["size"] for item in payload["files"]}
            for name in ROOT_ASSETS:
                self.assertIn(name, files)
            for required in (
                "VERSION",
                "LICENSE.md",
                "THIRD_PARTY_NOTICES.md",
                "COMPLIANCE.md",
                "ComfyUI/LAKIS/external_ui/app.js",
                "ComfyUI/LAKIS/external_ui/serve_ui.py",
                "ComfyUI/LAKIS/external_ui/workflow_bridge.py",
                "ComfyUI/LAKIS/install_snapref.py",
                "ComfyUI/LAKIS/external_ui/runtime/native_workflow.py",
                "ComfyUI/LAKIS/external_ui/workflows/LAKIS_custom_v8.0_editable.json",
                "ComfyUI/LAKIS/external_ui/workflows/LAKIS_runtime_api_v8.0.json",
                "ComfyUI/LAKIS/external_ui/workflows/LAKIS_runtime_visual_v8.0.json",
                "ComfyUI/LAKIS/workflows/LAKIS_runtime_api_v7.4.json",
                "ComfyUI/custom_nodes/ComfyUI-LAKIS-Detail/native_controls.py",
                "ComfyUI/custom_nodes/ComfyUI-LAKIS-Detail/web/native_workflow.js",
                "ComfyUI/custom_nodes/ComfyUI-LAKIS-Local-Inpaint/__init__.py",
                "ComfyUI/custom_nodes/ComfyUI-LAKIS-Regional-Reference/__init__.py",
            ):
                self.assertIn(required, files)

            forbidden_prefixes = (
                "ComfyUI/models/",
                "ComfyUI/user/",
                "ComfyUI/input/",
                "ComfyUI/output/",
            )
            self.assertFalse(any(path.startswith(forbidden_prefixes) for path in files))
            self.assertNotIn("ComfyUI/LAKIS/workflows/LAKIS_custom_v7.4_editable.json", files)
            self.assertNotIn("ComfyUI/LAKIS/workflows/LAKIS_custom_v8.0_editable.json", files)
            self.assertNotIn("ComfyUI/LAKIS/workflows/LAKIS_custom_v7.3_editable.json", payload["retired"])
            self.assertNotIn("ComfyUI/LAKIS/external_ui/release-integrity.json", files)
            self.assertIn(
                "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/__init__.py",
                payload["retired"],
            )

            with zipfile.ZipFile(pack) as archive:
                self.assertEqual(payload["version"].encode("utf-8"), archive.read("VERSION"))
                for name in ("LICENSE.md", "THIRD_PARTY_NOTICES.md", "COMPLIANCE.md"):
                    committed = subprocess.check_output(
                        ["git", "-C", str(ROOT), "show", f"HEAD:{name}"])
                    self.assertEqual(archive.read(name), committed, name)
                packed = {
                    info.filename.replace("\\", "/").rstrip("/"): info.file_size
                    for info in archive.infolist()
                    if not info.is_dir()
                }
            self.assertEqual(files, packed)

    def test_update_manifest_delivers_all_legal_documents_without_user_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dist = root / "dist"
            dist.mkdir()
            for name in ROOT_ASSETS:
                (dist / name).write_bytes(b"isolated binary fixture")
            output = root / "update.json"
            revision = "a" * 40
            version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                 str(INSTALLER / "New-UpdateManifest.ps1"), "-Version", version,
                 "-DistDirectory", str(dist), "-OutputPath", str(output),
                 "-SourceRevision", revision, "-UseLocalWorkingTreeHashes"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8-sig"))
            files = {entry["path"]: entry for entry in manifest["files"]}
            for name in ("LICENSE.md", "THIRD_PARTY_NOTICES.md", "COMPLIANCE.md"):
                self.assertEqual(files[name]["sha256"],
                                 hashlib.sha256((ROOT / name).read_bytes()).hexdigest().upper())
                self.assertEqual(files[name]["url"],
                                 f"https://raw.githubusercontent.com/Jeong-Luke/LAKIS/{revision}/{name}")
                self.assertNotIn(name, manifest["delete"])
            self.assertFalse(any(path.startswith(("ComfyUI/models/", "ComfyUI/user/",
                                                  "ComfyUI/input/", "ComfyUI/output/"))
                                 for path in files))

    def test_release_layout_cannot_package_windows_working_tree_bytes(self):
        script = LAYOUT_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("UseWorkingTree", script)
        self.assertIn("git -c core.autocrlf=false -C $repo archive", script)
        self.assertIn("Setup and Updater write VERSION without a trailing newline", script)

    def test_launcher_uses_size_consistency_and_fail_open_network_policy(self):
        launcher = (INSTALLER / "LAKIS_Launcher.cs").read_text(encoding="utf-8")
        self.assertIn("TryGetReleaseLayout", launcher)
        layout_method = launcher.index("private static bool TryGetReleaseLayout")
        layout_request = launcher.index("WebRequest.Create(", layout_method)
        tls_enable = launcher.index(
            "ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;",
            layout_method,
        )
        self.assertLess(tls_enable, layout_request)
        self.assertIn("new FileInfo(path).Length != entry.size", launcher)
        self.assertIn("GitHub와 설치 파일의 동일성 검사를 완료하지 못했습니다.", launcher)
        self.assertIn("동일성 검사 없이 LAKIS를 실행합니다.", launcher)
        self.assertIn("ScheduleAutomaticRepair", launcher)
        self.assertIn("UsesReleaseLayout(root)", launcher)
        self.assertIn("version >= new Version(7, 5, 0)", launcher)
        self.assertIn("LAKIS_RepairPack.zip", launcher)
        self.assertIn("release-layout-repair.attempt", launcher)
        argument_quote_start = launcher.index("private static string QuoteNativeArgument")
        argument_quote_end = launcher.index(
            "private static bool ScheduleAutomaticRepair", argument_quote_start
        )
        argument_quote = launcher[argument_quote_start:argument_quote_end]
        self.assertIn("backslashes * 2 + 1", argument_quote)
        self.assertIn("backslashes * 2", argument_quote)
        self.assertIn(
            "File.WriteAllText(helper, script, new UTF8Encoding(true));", launcher
        )
        self.assertIn("Repair post-check failed", launcher)
        self.assertIn("Repair retired-path post-check failed", launcher)
        self.assertIn("if((-not [IO.File]::Exists($dst))", launcher)
        self.assertIn("자동 복구에 실패했습니다.`nLAKIS Setup을 다시 실행하여 Repair를 진행해 주세요.", launcher)
        for path in (
            "ComfyUI/models",
            "ComfyUI/user",
            "ComfyUI/input",
            "ComfyUI/output",
        ):
            self.assertIn('"' + path + '"', launcher)
        self.assertIn(
            'normalized.StartsWith(directory + "/", StringComparison.OrdinalIgnoreCase)', launcher
        )
        self.assertNotIn("ReleaseIntegritySha256", launcher)
        self.assertNotIn("ComputeIntegrityHash", launcher)


@unittest.skipUnless(CSC.is_file(), "Windows .NET Framework compiler required")
class AutomaticRepairAttemptBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="lakis-repair-attempt-probe-")
        root = Path(cls.temp.name)
        probe_source = root / "probe.cs"
        probe_source.write_text(REPAIR_ATTEMPT_PROBE, encoding="utf-8")
        cls.exe = root / "probe.exe"
        command = [
            str(CSC), "/nologo", "/target:exe", "/main:RepairAttemptProbe",
            "/out:" + str(cls.exe),
            *["/reference:" + name for name in (
                "System.Windows.Forms.dll", "System.Drawing.dll",
                "System.Web.Extensions.dll", "System.IO.Compression.dll",
                "System.IO.Compression.FileSystem.dll")],
            str(INSTALLER / "SplashArtwork.cs"),
            str(INSTALLER / "UpdateProtocol.cs"),
            str(INSTALLER / "LAKIS_Launcher.cs"),
            str(probe_source),
        ]
        result = subprocess.run(command, capture_output=True, timeout=60)
        if result.returncode:
            cls.temp.cleanup()
            raise RuntimeError(
                result.stdout.decode(errors="replace") +
                result.stderr.decode(errors="replace")
            )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_probe(self, marker, version, *, locked=False):
        action = "locked" if locked else "check"
        result = subprocess.run(
            [str(self.exe), action, str(marker), version],
            capture_output=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return result.stdout.decode("ascii").strip() == "true"

    def test_marker_behavior_and_bytes_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / "release-layout-repair.attempt"
            self.assertFalse(self.run_probe(marker, "8.1.1"))
            self.assertFalse(marker.exists())

            cases = (
                ("matching", b"8.1.1", True),
                ("different", b"8.1.0", False),
                ("malformed", b"not-a-version", True),
                ("empty", b"", True),
            )
            for name, contents, expected in cases:
                with self.subTest(name=name):
                    marker.write_bytes(contents)
                    before = marker.read_bytes()
                    self.assertEqual(self.run_probe(marker, "8.1.1"), expected)
                    self.assertEqual(marker.read_bytes(), before)

            marker.write_bytes(b"8.1.1")
            before = marker.read_bytes()
            self.assertTrue(self.run_probe(marker, "8.1.1", locked=True))
            self.assertEqual(marker.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
