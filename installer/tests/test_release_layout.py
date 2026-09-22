import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "installer"
LAYOUT_SCRIPT = INSTALLER / "New-ReleaseLayout.ps1"

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
                "-UseWorkingTree",
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
            self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), payload["version"])

            files = {item["path"]: item["size"] for item in payload["files"]}
            for name in ROOT_ASSETS:
                self.assertIn(name, files)
            for required in (
                "VERSION",
                "LICENSE.md",
                "THIRD_PARTY_NOTICES.md",
                "ComfyUI/LAKIS/external_ui/app.js",
                "ComfyUI/LAKIS/external_ui/serve_ui.py",
                "ComfyUI/LAKIS/external_ui/workflow_bridge.py",
                "ComfyUI/LAKIS/workflows/LAKIS_runtime_api_v7.4.json",
                "ComfyUI/custom_nodes/ComfyUI-LAKIS-Local-Inpaint/__init__.py",
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
            self.assertNotIn("ComfyUI/LAKIS/workflows/LAKIS_custom_v7.3_editable.json", payload["retired"])
            self.assertNotIn("ComfyUI/LAKIS/external_ui/release-integrity.json", files)
            self.assertIn(
                "ComfyUI/custom_nodes/ComfyUI-LAKIS-Light-Control/__init__.py",
                payload["retired"],
            )

            with zipfile.ZipFile(pack) as archive:
                packed = {
                    info.filename.replace("\\", "/").rstrip("/"): info.file_size
                    for info in archive.infolist()
                    if not info.is_dir()
                }
            self.assertEqual(files, packed)

    def test_launcher_uses_size_consistency_and_fail_open_network_policy(self):
        launcher = (INSTALLER / "LAKIS_Launcher.cs").read_text(encoding="utf-8")
        self.assertIn("TryGetReleaseLayout", launcher)
        self.assertIn("new FileInfo(path).Length != entry.size", launcher)
        self.assertIn("GitHub와 설치 파일의 동일성 검사를 완료하지 못했습니다.", launcher)
        self.assertIn("동일성 검사 없이 LAKIS를 실행합니다.", launcher)
        self.assertIn("ScheduleAutomaticRepair", launcher)
        self.assertIn("UsesReleaseLayout(root)", launcher)
        self.assertIn("version >= new Version(7, 5, 0)", launcher)
        self.assertIn("LAKIS_RepairPack.zip", launcher)
        self.assertIn("release-layout-repair.attempt", launcher)
        self.assertIn("Repair post-check failed", launcher)
        self.assertIn("Repair retired-path post-check failed", launcher)
        self.assertIn("if((-not [IO.File]::Exists($dst))", launcher)
        self.assertIn("자동 복구에 실패했습니다.`nLAKIS Setup을 다시 실행하여 Repair를 진행해 주세요.", launcher)
        for path in (
            "ComfyUI/models/",
            "ComfyUI/user/",
            "ComfyUI/input/",
            "ComfyUI/output/",
        ):
            self.assertIn(path, launcher)
        self.assertNotIn("ReleaseIntegritySha256", launcher)
        self.assertNotIn("ComputeIntegrityHash", launcher)


if __name__ == "__main__":
    unittest.main(verbosity=2)
