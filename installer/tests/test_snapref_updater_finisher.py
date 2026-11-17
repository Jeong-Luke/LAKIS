"""Run the native finisher with disposable files and offline executable stubs."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "installer"))
import build_updater_bridge as native


@unittest.skipUnless(os.name == "nt", "Windows native finisher required")
class SnapRefUpdaterFinisherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(cls.enterClassContext(tempfile.TemporaryDirectory(prefix="lakis-snapref-finisher-")))
        updater_source = ROOT / "installer/LAKIS_Updater.cs"
        cls.updater = cls.work / "LAKIS_Updater.exe"
        native.compile_native(cls.updater, [updater_source])
        cls.harness = cls.work / "SnapRefUpdaterFinisherContract.exe"
        native.compile_native(
            cls.harness, [updater_source, Path(__file__).with_name("SnapRefUpdaterFinisherContract.cs")],
            main="SnapRefUpdaterFinisherContract",
        )

    def fixture(self, scenario):
        install = self.work / f"{scenario} 테스트 install"
        for directory in ("ComfyUI/LAKIS", "ComfyUI/user", "ComfyUI/models/loras", ".lakis"):
            (install / directory).mkdir(parents=True)
        (install / "VERSION").write_text(
            "8.1.1" if scenario == "other-source" else "8.1.2", encoding="ascii")
        (install / "LAKIS_Patcher.exe").write_bytes(b"old updater")
        shutil.copyfile(self.harness, install / "LAKIS.exe")
        (install / "ComfyUI/main.py").write_bytes(b"# never run\n")
        if scenario != "missing-script":
            (install / "ComfyUI/LAKIS/install_snapref.py").write_bytes(b"# never run\n")
        if scenario == "download-and-launch":
            shutil.copyfile(self.harness, install / "LAKIS_Updater.exe")
        if scenario == "failure":
            (install / "fail-python").touch()
        if scenario == "installed":
            node = install / "ComfyUI/custom_nodes/snapref/__init__.py"
            node.parent.mkdir(parents=True)
            node.touch()
            (install / "ComfyUI/models/loras/snapref_v2a.safetensors").touch()
        python = install / "python_embeded"
        if scenario == "linked-python":
            import _winapi
            outside = self.work / "outside Python"
            outside.mkdir()
            shutil.copyfile(self.harness, outside / "python.exe")
            _winapi.CreateJunction(str(outside), str(python))
        else:
            python.mkdir()
            shutil.copyfile(self.harness, python / "python.exe")
        (install / "ComfyUI/user/settings.json").write_bytes(b'{"keep": true}')
        return install

    def run_contract(self, scenario):
        install = self.fixture(scenario)
        result = subprocess.run(
            [str(self.harness), scenario, str(install)], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(list((install / ".lakis").iterdir()), [install / ".lakis/self-update-retired"])
        self.assertEqual(list((install / "ComfyUI/user").iterdir()), [install / "ComfyUI/user/settings.json"])
        self.assertEqual((install / "ComfyUI/user/settings.json").read_bytes(), b'{"keep": true}')

    def test_stock_finisher_downloads_only_after_commit_with_or_without_relaunch(self):
        for scenario in ("download", "download-and-launch"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)

    def test_skip_close_and_explicit_retry(self):
        for scenario in ("close", "retry", "installed"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)

    def test_optional_failure_preserves_core_and_relaunch(self):
        for scenario in ("failure", "missing-script", "linked-python"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)

    def test_unrelated_or_unattended_finishes_do_not_offer(self):
        for scenario in ("noninteractive", "repair", "later-version", "other-source", "no-handoff"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)
        # Also exercise the normally compiled updater's real CLI entry point:
        # even with the stock source/target and a positive PID, headless is quiet.
        install = self.fixture("headless")
        subprocess.run(
            [str(self.updater), "--finish-self-update", str(install), "8.1.3", "2147483647",
             "--self-name=LAKIS_Patcher.exe", "--headless"], check=True, timeout=20)
        self.assertEqual((install / "VERSION").read_text(encoding="ascii"), "8.1.3")
        self.assertEqual((install / "LAKIS_Patcher.exe").read_bytes(), self.updater.read_bytes())
        self.assertFalse((install / "python-ran").exists())


if __name__ == "__main__":
    unittest.main()
