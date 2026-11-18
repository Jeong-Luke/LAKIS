"""Run the 8.1.3.2 native finisher with disposable files and offline fixtures."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "installer"))
from build_813_file_patch import canonical_source, git
import build_updater_bridge as native


RUNTIME_813_SOURCE = "4ebaa03c1e50f1cfbe0cfc1dceb42915719c3fea"
OVERLAY = {
    "ComfyUI/LAKIS/external_ui/index.html": "src/external_ui/index.html",
    "ComfyUI/LAKIS/external_ui/anima-reference.js": "src/external_ui/anima-reference.js",
    "ComfyUI/LAKIS/external_ui/anima-reference.css": "src/external_ui/anima-reference.css",
    "COMPLIANCE.md": "COMPLIANCE.md",
}
UNCOMMITTED = {
    "cancel", "linked-python", "bad-helper", "too-old", "already-target", "no-handoff",
    "runtime-fails", "runtime-bad-descriptor", "runtime-bad-overlay", "runtime-restore-blocked",
    "notice-restore-blocked", "notice-bad-asset", "runtime-notice-bad-asset",
}


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
        cls.runtime_overlay = cls.work / "runtime-813-overlay"
        cls.patch_overlay = {path: canonical_source(source) for path, source in OVERLAY.items()}
        cls.notice = cls.work / "official-8132-COMPLIANCE.md"
        cls.notice.write_bytes(cls.patch_overlay["COMPLIANCE.md"])
        for path, source in OVERLAY.items():
            old = git("show", f"{RUNTIME_813_SOURCE}:{source}")
            if old == cls.patch_overlay[path]:
                raise AssertionError(f"8.1.3 fixture must differ from the 8.1.3.2 payload: {path}")
            destination = cls.runtime_overlay / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(old)

    def fixture(self, scenario):
        install = self.work / f"{scenario} 테스트 install"
        for directory in ("ComfyUI/LAKIS", "ComfyUI/user", "ComfyUI/models/loras", ".lakis"):
            (install / directory).mkdir(parents=True)
        source = {
            "runtime-810": "8.1.0", "runtime-no-launch": "8.1.1", "too-old": "8.0.3",
            "stock": "8.1.3.1", "stock-live": "8.1.3.1", "already-target": "8.1.3.2",
        }.get(scenario, "8.1.2" if scenario.startswith("runtime-") else "8.1.3")
        (install / "VERSION").write_text(source, encoding="ascii")
        patcher = install / "LAKIS_Patcher.exe"
        if scenario == "stock-live":
            shutil.copyfile(self.harness, patcher)
        else:
            patcher.write_bytes(b"old updater")
        shutil.copyfile(self.harness, install / "LAKIS.exe")
        (install / "ComfyUI/main.py").write_bytes(b"# never run\n")
        if scenario == "stock":
            shutil.copyfile(self.helper, install / "ComfyUI/LAKIS/install_snapref.py")
        elif scenario != "missing-script":
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
        (install / "ComfyUI/models/loras/user-model.safetensors").write_bytes(b"user model")
        for path, data in self.patch_overlay.items():
            destination = install / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Only the three UI files are in the common stock file patch.
            destination.write_bytes((self.runtime_overlay / path).read_bytes() if path == "COMPLIANCE.md" else data)
        if scenario == "runtime-bad-overlay":
            path = "ComfyUI/LAKIS/external_ui/index.html"
            shutil.copyfile(self.runtime_overlay / path, install / path)
        return install

    def run_contract(self, scenario):
        install = self.fixture(scenario)
        result = subprocess.run(
            [str(self.harness), scenario, str(install), str(self.helper), str(self.descriptor),
             str(self.runtime_overlay), str(self.notice)],
            capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        retired = [install / ".lakis/self-update-retired"]
        self.assertEqual(
            list((install / ".lakis").iterdir()),
            [] if scenario in UNCOMMITTED else retired,
        )
        self.assertEqual(list((install / "ComfyUI/user").iterdir()), [install / "ComfyUI/user/settings.json"])
        self.assertEqual((install / "ComfyUI/user/settings.json").read_bytes(), b'{"keep": true}')
        self.assertEqual((install / "ComfyUI/models/loras/user-model.safetensors").read_bytes(), b"user model")
        for path, new in self.patch_overlay.items():
            old = scenario == "runtime-restore-blocked" or (
                scenario == "runtime-bad-overlay" and path.endswith("/index.html")) or (
                path == "COMPLIANCE.md" and (scenario in UNCOMMITTED or scenario == "later-version"))
            self.assertEqual((install / path).read_bytes(), (self.runtime_overlay / path).read_bytes() if old else new, path)
        self.assertFalse(list(install.rglob("*.lakis-8132-*")), "Overlay transaction left temporary files")
        observed = install / "launcher-overlay"
        if observed.exists():
            self.assertEqual(observed.read_text(encoding="ascii").splitlines(),
                             [hashlib.sha256(data).hexdigest().upper() for data in self.patch_overlay.values()])
        return install

    def test_813_and_stock_8131_finish_directly_with_or_without_relaunch(self):
        for scenario in ("stock-live", "legacy-alias", "missing-script"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)

    def test_stock_8131_runs_the_real_pinned_helper_without_rewriting_version_or_accepting_terms(self):
        install = self.run_contract("stock")
        argv = json.loads((install / "python-args.json").read_bytes())
        version = install / "VERSION"
        version.write_bytes(b"8.1.3.1")
        weight = install / "ComfyUI/models/loras/snapref_v2a.safetensors"
        weight.write_bytes(b"conflicting local weight")
        # The real helper must pass its version check and turn down the
        # conflicting local file before attempting any publisher request.
        result = subprocess.run([sys.executable, *argv], cwd=install, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"Existing SnapRef model differs; it was not overwritten", result.stderr)
        self.assertEqual(version.read_bytes(), b"8.1.3.1")
        self.assertEqual(weight.read_bytes(), b"conflicting local weight")
        self.assertEqual((install / "ComfyUI/LAKIS/install_snapref.py").read_bytes(), self.helper.read_bytes())

    def test_retry_completes_the_same_handoff(self):
        self.run_contract("retry")

    def test_failed_preparation_does_not_commit_or_relaunch(self):
        for scenario in ("cancel", "bad-helper", "linked-python"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)

    def test_unrelated_or_unattended_finishes_do_not_provision(self):
        for scenario in ("headless", "noninteractive", "repair", "later-version", "too-old",
                         "already-target", "no-handoff"):
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
        self.assertEqual((install / "COMPLIANCE.md").read_bytes(),
                         (self.runtime_overlay / "COMPLIANCE.md").read_bytes())

    def test_legacy_sources_restore_exact_patch_bytes_after_verified_runtime_activation(self):
        for scenario in ("runtime-810", "runtime-no-launch", "runtime-812"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)

    def test_invalid_descriptor_or_runtime_failure_blocks_hotfix_and_relaunch(self):
        for scenario in ("runtime-bad-descriptor", "runtime-fails"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)

    def test_wrong_preapplied_bytes_or_blocked_restore_fail_closed(self):
        for scenario in ("runtime-bad-overlay", "runtime-restore-blocked"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)

    def test_bad_official_notice_and_blocked_direct_install_fail_closed(self):
        for scenario in ("notice-bad-asset", "runtime-notice-bad-asset", "notice-restore-blocked"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)

    def test_exact_installed_notice_is_reused_on_both_routes(self):
        for scenario in ("notice-reuse", "runtime-notice-reuse"):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)


if __name__ == "__main__":
    unittest.main()
