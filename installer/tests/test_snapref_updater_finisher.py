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
        cls.helper = cls.work / "install_snapref.py"
        cls.helper.write_bytes((ROOT / "installer/install_snapref_experiment.py").read_bytes().replace(b"\r\n", b"\n"))
        cls.descriptor = cls.work / "public-813-runtime.json"
        cls.descriptor.write_bytes(Path(__file__).with_name("fixtures").joinpath(
            "hotfix-public-813-runtime.json").read_bytes().replace(b"\r\n", b"\n"))

    def fixture(self, scenario):
        install = self.work / f"{scenario} 테스트 install"
        for directory in ("ComfyUI/LAKIS", "ComfyUI/user", "ComfyUI/models/loras", ".lakis"):
            (install / directory).mkdir(parents=True)
        source = {"runtime-810": "8.1.0", "runtime-no-launch": "8.1.1", "too-old": "8.0.3"}.get(
            scenario, "8.1.2" if scenario.startswith("runtime-") else "8.1.3")
        (install / "VERSION").write_text(source, encoding="ascii")
        (install / "LAKIS_Patcher.exe").write_bytes(b"old updater")
        shutil.copyfile(self.harness, install / "LAKIS.exe")
        (install / "ComfyUI/main.py").write_bytes(b"# never run\n")
        if scenario != "missing-script":
            (install / "ComfyUI/LAKIS/install_snapref.py").write_bytes(b"# old helper\n")
        if scenario == "legacy-alias":
            shutil.copyfile(self.harness, install / "LAKIS_Updater.exe")
        if scenario in ("cancel", "retry"):
            (install / "fail-python-once").touch()
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
            [str(self.harness), scenario, str(install), str(self.helper), str(self.descriptor)],
            capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        retired = [install / ".lakis/self-update-retired"]
        self.assertEqual(
            list((install / ".lakis").iterdir()),
            [] if scenario in ("cancel", "linked-python", "bad-helper", "too-old", "no-handoff",
                               "runtime-fails", "runtime-bad-descriptor") else retired,
        )
        self.assertEqual(list((install / "ComfyUI/user").iterdir()), [install / "ComfyUI/user/settings.json"])
        self.assertEqual((install / "ComfyUI/user/settings.json").read_bytes(), b'{"keep": true}')

    def test_stock_finisher_provisions_before_commit_with_or_without_relaunch(self):
        for scenario in ("stock", "legacy-alias", "missing-script"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)

    def test_retry_completes_the_same_handoff(self):
        self.run_contract("retry")

    def test_failed_preparation_does_not_commit_or_relaunch(self):
        for scenario in ("cancel", "bad-helper", "linked-python"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)

    def test_unrelated_or_unattended_finishes_do_not_provision(self):
        for scenario in ("headless", "noninteractive", "repair", "later-version", "too-old", "no-handoff"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)
        # Also exercise the normally compiled updater's real CLI entry point
        # for an unrelated handoff that must not contact the hotfix endpoint.
        install = self.fixture("cli-unrelated")
        subprocess.run(
            [str(self.updater), "--finish-self-update", str(install), "8.1.4", "2147483647",
             "--self-name=LAKIS_Patcher.exe", "--headless"], check=True, timeout=20)
        self.assertEqual((install / "VERSION").read_text(encoding="ascii"), "8.1.4")
        self.assertEqual((install / "LAKIS_Patcher.exe").read_bytes(), self.updater.read_bytes())
        self.assertFalse((install / "python-ran").exists())

    def test_legacy_sources_dispatch_one_verified_runtime_then_resume_hotfix(self):
        for scenario in ("runtime-810", "runtime-no-launch", "runtime-812"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)

    def test_invalid_descriptor_or_runtime_failure_blocks_hotfix_and_relaunch(self):
        for scenario in ("runtime-bad-descriptor", "runtime-fails"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)


if __name__ == "__main__":
    unittest.main()
