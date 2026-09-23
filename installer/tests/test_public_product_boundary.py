import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest


REPO = Path(__file__).resolve().parents[2]
EXTERNAL = REPO / "src" / "external_ui"


class PublicProductBoundaryTests(unittest.TestCase):
    def read(self, relative):
        return (REPO / relative).read_text(encoding="utf-8")

    def test_manifest_generator_blocks_private_product_paths(self):
        text = self.read("installer/New-UpdateManifest.ps1")
        self.assertIn("forbiddenProductPathPattern", text)
        for token in (
            "LAKIS_DEV", "DEKIS", "LUKIS", "LAKIS_LUKE",
            "DEV_VERSION", "LUKE_VERSION", "LAKIS_DEV_red",
            "LUKIS_Desktop", "Start_LUKIS_Mobile",
        ):
            self.assertIn(token, text)

    def test_public_build_and_release_assets_exclude_dev_outputs(self):
        build = self.read("installer/build_safe_installer.ps1")
        workflow = self.read(".github/workflows/publish-installer.yml")
        for token in (
            "/define:LAKIS_DEV", "/define:LAKIS_LUKE",
            "LAKIS_DEV.exe", "LAKIS_DEV_Desktop.exe",
            "LUKIS_Desktop.exe", "Start_LUKIS_Mobile.cmd",
        ):
            self.assertNotIn(token, build)
        for token in (
            "LAKIS_DEV.exe", "LAKIS_DEV_Desktop.exe",
            "LUKIS_Desktop.exe", "Start_LUKIS_Mobile.cmd",
        ):
            self.assertNotIn(token, workflow)

    def test_boundary_scan_covers_every_public_executable(self):
        boundary = self.read("installer/Test-PublicProductBoundary.ps1")
        for binary in (
            "LAKIS.exe", "LAKIS_Patcher.exe", "LAKIS_Updater.exe",
            "LAKIS_Desktop.exe", "LAKIS_Model_Importer.exe",
            "Uninstall_LAKIS.exe", "LAKIS_Setup.exe",
        ):
            self.assertIn(f'"{binary}"', boundary)
        self.assertIn('Get-ChildItem -LiteralPath $dist -File -Filter "*.exe"', boundary)
        # Paths reject all private identities. Binary tokens are narrower:
        # defensive environment-variable resets are not private executables.
        path_match = re.search(r"\$forbiddenPathPattern = '([^']+)'", boundary)
        strict_match = re.search(r"\$strictTokens = @\((.*?)\n\)", boundary, re.S)
        self.assertIsNotNone(path_match)
        self.assertIsNotNone(strict_match)
        for token in (
            "LAKIS_DEV", "LAKIS_LUKE", "DEKIS", "LUKIS",
            "DEV_VERSION", "LUKE_VERSION", "LAKIS_DEV_red",
            "LUKIS_Desktop", "Start_LUKIS_Mobile",
        ):
            self.assertIn(token, path_match.group(1))
        for token in (
            "DEKIS", "LUKIS", "LAKIS Studio DEV", "LUKIS Studio",
            "LAKIS_DEV_Desktop.exe", "LUKIS_Desktop.exe",
            "Start_LUKIS_Mobile.cmd", "DEV_VERSION", "LUKE_VERSION",
            ".lakis-dev", ".lukis",
        ):
            self.assertIn(f'"{token}"', strict_match.group(1))
        for token in ("LAKIS_DEV", "LAKIS_LUKE"):
            self.assertNotIn(f'"{token}"', strict_match.group(1))

    def test_public_setup_has_no_dev_or_private_product_labels(self):
        setup = self.read("installer/Setup_LAKIS_Safe.cs")
        self.assertNotIn("DEKIS", setup)
        self.assertNotIn("LUKIS", setup)

    def test_public_managed_providers_have_no_dekis_or_lukis_registration(self):
        packages = [
            line.strip()
            for line in self.read("resources/PRODUCTION_NODE_PACKAGES.txt").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        for package in packages:
            root = REPO / "src" / "custom_nodes" / package
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in {".py", ".js", ".json"}:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotRegex(text, r"(?i)DEKIS_|LUKIS_|LAKIS_LUKE", str(path))

    def test_public_ui_has_no_visible_dev_identity(self):
        advanced = self.read("src/external_ui/advanced-node-settings.js")
        bridge = self.read("src/external_ui/workflow_bridge.py")
        app = self.read("src/external_ui/app.js")
        self.assertIn("exposure_outfit_edit = (\n        DEVELOPMENT", bridge)
        self.assertNotIn("LAKIS DEV</small>", advanced)
        self.assertNotIn('"LAKIS DEV - Turbo Initial"', bridge)
        self.assertIn('const PROMPT_STORAGE_KEY = "lakis.promptState.v3";', app)
        self.assertEqual(app.count("lakis.dekis.promptState.v1"), 1)

    def test_public_launcher_neutralizes_inherited_private_environment(self):
        launcher = self.read("installer/LAKIS_Launcher.cs")
        for assignment in (
            '["LAKIS_DEVELOPMENT"] = "0"',
            '["LAKIS_LUKE"] = "0"',
            '["LAKIS_FULL_TURBO_EXPERIMENT"] = "0"',
            '["LAKIS_HALF_RES_FAST_EXPERIMENT"] = "0"',
            '["LAKIS_LOCAL_INPAINT_V2"] = "1"',
            '["LAKIS_COMFY_PORT"] = "8189"',
        ):
            self.assertIn(assignment, launcher)
        self.assertIn('Path.Combine(root, "LAKIS_Desktop.exe")', launcher)

    def probe_runtime(self, runtime_name):
        with tempfile.TemporaryDirectory() as temp:
            ext = Path(temp) / "ComfyUI" / runtime_name / "external_ui"
            ext.mkdir(parents=True)
            for name in ("launch_lakis.py", "workflow_bridge.py", "serve_ui.py"):
                shutil.copy2(EXTERNAL / name, ext / name)
            code = (
                "import json,sys,types; "
                "sys.modules['aiohttp']=types.ModuleType('aiohttp'); "
                f"sys.path.insert(0, {str(ext)!r}); "
                "import launch_lakis,workflow_bridge,serve_ui; "
                "print(json.dumps({"
                "'launch':launch_lakis.DEVELOPMENT,'bridge':workflow_bridge.DEVELOPMENT,"
                "'server':serve_ui.DEVELOPMENT,'launch_port':launch_lakis.COMFY_PORT,"
                "'bridge_port':workflow_bridge.COMFY_PORT,'server_port':serve_ui.COMFY_PORT,"
                "'desktop':str(launch_lakis.DESKTOP_HOST)}))"
            )
            env = os.environ.copy()
            env.update({
                "LAKIS_DEVELOPMENT": "1",
                "LAKIS_COMFY_PORT": "65500",
                "LAKIS_DESKTOP_HOST": r"C:\fake\LAKIS_DEV_Desktop.exe",
            })
            result = subprocess.run(
                [sys.executable, "-c", code], env=env, text=True,
                capture_output=True, check=True,
            )
            return json.loads(result.stdout.strip().splitlines()[-1])

    def test_public_runtime_fails_closed_even_with_dev_environment(self):
        result = self.probe_runtime("LAKIS")
        self.assertFalse(result["launch"])
        self.assertFalse(result["bridge"])
        self.assertFalse(result["server"])
        self.assertEqual((result["launch_port"], result["bridge_port"], result["server_port"]), (8189, 8189, 8189))
        self.assertTrue(result["desktop"].endswith("LAKIS_Desktop.exe"))
        self.assertNotIn("LAKIS_DEV_Desktop.exe", result["desktop"])

    def test_dev_runtime_still_requires_dev_folder(self):
        result = self.probe_runtime("LAKIS_DEV")
        self.assertTrue(result["launch"] and result["bridge"] and result["server"])
        self.assertEqual((result["launch_port"], result["bridge_port"], result["server_port"]), (65500, 65500, 65500))


if __name__ == "__main__":
    unittest.main(verbosity=2)
