"""Exercise MOSS model delivery without touching an installed LAKIS or large weights."""
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import test_cmd_installer as fixtures
import lakis_cmd_installer as downloader
import runtime_install
import runtime_manifest as contract
import runtime_patch
import runtime_transition
import runtime_update


ROOT = Path(__file__).resolve().parents[2]
CSC = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"


def snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


class MossModelUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lakis-model-update-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidate, installer = fixtures.CmdInstallerTests()._runtime_candidate(self.root)
        self.target = self.root / "installed"
        shutil.copytree(self.candidate, self.target)
        (self.target / "VERSION").write_text("8.0.3", encoding="ascii")
        for relative in ("ComfyUI/output/keep.png", "ComfyUI/models/loras/user.safetensors",
                         "ComfyUI/user/default/workflows/user.json", ".lakis/settings.json"):
            path = self.target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("user data: " + relative).encode())
        self.before = snapshot(self.target)
        self.cache = self.root / "cache"
        self.manifest = {
            "schema": 2, "kind": "runtime-update", "version": "8.1.0",
            "minimum_version": "8.0.0", "minimum_updater_version": "8.1.0",
            "files": [], "delete": [], "runtime_bundle": installer["runtime_bundle"],
        }
        self.specs = {}
        for index, (relative, spec) in enumerate(contract.required_model_specs("8.1.0").items()):
            payload = ("independent model fixture " + str(index)).encode()
            source = self.root / ("model-" + str(index))
            source.write_bytes(payload)
            self.specs[relative] = {
                **spec, "url": source.as_uri(), "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest().upper(),
            }
        self.stack = self.enterContext(ExitStack())
        self.stack.enter_context(mock.patch("sys.stdout", io.StringIO()))

    def local_models(self):
        return self.stack.enter_context(mock.patch.object(
            contract, "required_model_specs", return_value=self.specs))

    def prepare(self):
        return runtime_install.prepare_required_models(self.cache, self.target, "8.1.0")

    def update(self, **kwargs):
        return runtime_update.run(self.manifest, self.target, self.cache, **kwargs)

    def isolate_health(self):
        self.stack.enter_context(mock.patch.object(runtime_patch, "assert_idle"))
        self.stack.enter_context(mock.patch.object(runtime_patch, "check_runtime"))

    def assert_original_files(self):
        current = snapshot(self.target)
        self.assertEqual({key: current[key] for key in self.before}, self.before)

    def test_moss_pins_match_installer_source_and_legacy_versions_stay_separate(self):
        installer = json.loads((ROOT / "installer/cmd-installer-manifest.json").read_text())
        source = {"ComfyUI/models/" + row[3] + "/" + row[0]: {
            "name": row[0], "url": row[1], "sha256": row[2], "size": row[4]
        } for row in installer["models"]}
        self.assertEqual(set(contract.MOSS_MODELS), {
            "ComfyUI/models/diffusion_models/moss_image_sft_int8_convrot.safetensors",
            "ComfyUI/models/text_encoders/qwen3.5_9b_int8_convrot.safetensors",
            "ComfyUI/models/vae/flux2-vae.safetensors",
        })
        for relative, spec in contract.MOSS_MODELS.items():
            self.assertEqual(spec, source[relative])
            self.assertRegex(spec["url"], r"/resolve/[a-f0-9]{40}/")
        self.assertEqual(contract.required_model_specs("8.0.3"), contract.POSE_MODELS)
        self.assertEqual(contract.required_model_specs("8.1.0"),
                         {**contract.POSE_MODELS, **contract.MOSS_MODELS})
        for version in ("8.1", "../8.1.0", None):
            with self.subTest(version=version), self.assertRaises(ValueError):
                contract.required_model_specs(version)

    def test_prepare_and_apply_downloads_all_dependencies_without_early_install_changes(self):
        self.local_models()
        self.isolate_health()
        with mock.patch.object(runtime_update, "prepare_bundle", return_value=self.candidate):
            prepared = self.update(prepare_only=True)
        self.assertEqual(prepared["status"], "prepared")
        self.assertEqual(snapshot(self.target), self.before)
        # Apply must work offline using the already verified cache.
        with mock.patch.object(downloader.urllib.request, "urlopen",
                               side_effect=AssertionError("unexpected network download")):
            result = self.update(prepared_root=self.candidate)
        self.assertEqual(result["status"], "complete")
        self.assertCountEqual(result["added_models"], self.specs)
        self.assertEqual((self.target / "VERSION").read_text(), "8.1.0")
        for relative, spec in self.specs.items():
            self.assertEqual(downloader.sha256(self.target / relative), spec["sha256"])
        for relative, data in self.before.items():
            if relative.startswith(("ComfyUI/models/", "ComfyUI/output/", "ComfyUI/user/", ".lakis/")):
                self.assertEqual((self.target / relative).read_bytes(), data)

    def test_existing_matching_models_are_reused_without_network_or_replacement(self):
        self.local_models()
        for relative, spec in self.specs.items():
            destination = self.target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = Path(downloader.urllib.request.url2pathname(
                downloader.urllib.parse.urlsplit(spec["url"]).path))
            shutil.copyfile(source, destination)
        before = snapshot(self.target)
        with mock.patch.object(runtime_install, "download") as download:
            files = self.prepare()
        download.assert_not_called()
        self.assertEqual(contract.model_dependency_rows(files, self.target, "8.1.0"), [])
        self.assertEqual(snapshot(self.target), before)

    def test_existing_conflicting_model_aborts_before_any_download(self):
        self.local_models()
        relative = next(reversed(self.specs))
        destination = self.target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"owner's different model")
        before = snapshot(self.target)
        with mock.patch.object(runtime_install, "download") as download, \
                self.assertRaisesRegex(ValueError, "이름 충돌"):
            self.prepare()
        download.assert_not_called()
        self.assertEqual(snapshot(self.target), before)

    def test_low_space_counts_cache_and_model_staging_together(self):
        self.local_models()
        model_bytes = sum(row["size"] for row in self.specs.values())
        disk = mock.Mock(free=model_bytes)
        with mock.patch.object(runtime_install.shutil, "disk_usage", return_value=disk), \
                mock.patch.object(runtime_install, "download") as download, \
                self.assertRaisesRegex(RuntimeError, "공간이 부족"):
            self.prepare()
        download.assert_not_called()
        self.assertEqual(snapshot(self.target), self.before)

    def test_download_failure_leaves_installation_unchanged(self):
        self.local_models()
        with mock.patch.object(runtime_install, "download", side_effect=OSError("offline")), \
                self.assertRaisesRegex(OSError, "offline"):
            self.prepare()
        self.assertEqual(snapshot(self.target), self.before)

    def test_tampered_cache_and_incomplete_model_set_cannot_activate(self):
        self.local_models()
        self.isolate_health()
        files = self.prepare()
        with self.assertRaisesRegex(ValueError, "download set"):
            contract.model_dependency_rows(dict(list(files.items())[:-1]), self.target, "8.1.0")
        files[next(iter(files))].write_bytes(b"changed after download")
        with self.assertRaisesRegex(ValueError, "verification"):
            runtime_patch.activate(self.candidate, self.target,
                self.manifest["runtime_bundle"]["manifest_sha256"], "8.1.0", model_files=files)
        self.assertEqual(snapshot(self.target), self.before)

    def test_activation_low_space_keeps_original_installation(self):
        self.local_models()
        self.isolate_health()
        files = self.prepare()
        with mock.patch.object(runtime_patch.shutil, "disk_usage", side_effect=[
                mock.Mock(free=1024 ** 3), mock.Mock(free=0)]), \
                self.assertRaisesRegex(RuntimeError, "model staging"):
            runtime_patch.activate(self.candidate, self.target,
                self.manifest["runtime_bundle"]["manifest_sha256"], "8.1.0", model_files=files)
        self.assertEqual(snapshot(self.target), self.before)

    def test_health_failure_rolls_back_programs_but_retains_added_models(self):
        self.local_models()
        self.isolate_health()
        with mock.patch.object(runtime_patch, "check_runtime", side_effect=RuntimeError("health failed")), \
                self.assertRaisesRegex(RuntimeError, "health failed"):
            self.update(prepared_root=self.candidate)
        self.assert_original_files()
        for relative, spec in self.specs.items():
            self.assertEqual(downloader.sha256(self.target / relative), spec["sha256"])
        self.assertEqual(runtime_transition._load_journal(self.target)["phase"], "rolled-back")
        # The next attempt can complete without downloading the same models again.
        with mock.patch.object(runtime_install, "download") as download:
            result = self.update(prepared_root=self.candidate)
        download.assert_not_called()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["added_models"], [])

    def test_interrupted_promotion_can_recover_and_preserves_new_user_output(self):
        self.local_models()
        self.isolate_health()
        write_journal = runtime_patch._write_journal

        class SimulatedCrash(BaseException):
            pass

        def crash_after_promotion(target, state):
            write_journal(target, state)
            if state["phase"] == "checking":
                raise SimulatedCrash()

        with mock.patch.object(runtime_patch, "_write_journal", side_effect=crash_after_promotion), \
                self.assertRaises(SimulatedCrash):
            self.update(prepared_root=self.candidate)
        new_output = self.target / "ComfyUI/output/new-user-image.png"
        new_output.write_bytes(b"created after interrupted update")
        result = self.update(prepared_root=self.candidate, rollback=True)
        self.assertEqual(result["status"], "rolled-back")
        self.assert_original_files()
        self.assertEqual(new_output.read_bytes(), b"created after interrupted update")
        for relative, spec in self.specs.items():
            self.assertEqual(downloader.sha256(self.target / relative), spec["sha256"])

    def test_81_manifest_requires_model_capable_updater(self):
        self.assertEqual(runtime_update.validate_update(self.manifest), self.manifest["runtime_bundle"])
        self.manifest["minimum_updater_version"] = "8.0.0"
        with self.assertRaisesRegex(ValueError, "8.1.0"):
            runtime_update.validate_update(self.manifest)

    def test_fresh_defaults_include_both_editable_workflows_without_touching_installation(self):
        anima = self.candidate / "ComfyUI/LAKIS/workflows/LAKIS_custom_v7.4_editable.json"
        moss = self.candidate / "ComfyUI/LAKIS/external_ui/workflows/LAKIS_MOSS_custom_v8.1_editable.json"
        anima.parent.mkdir(parents=True, exist_ok=True)
        moss.parent.mkdir(parents=True, exist_ok=True)
        anima.write_bytes(b"anima editable fixture")
        moss.write_bytes(b"moss editable fixture")
        with mock.patch.object(contract, "POSE_MODELS", {}), \
                mock.patch.object(runtime_install, "create_default_input_image"):
            defaults = runtime_install.prepare_default_data(
                self.candidate, {"version": "8.1.0", "models": []}, self.cache, "cmd")
        workflows = defaults / "ComfyUI/user/default/workflows"
        self.assertEqual((workflows / "LAKIS_custom_v7.4.json").read_bytes(), b"anima editable fixture")
        self.assertEqual((workflows / "LAKIS_MOSS_custom_v8.1.json").read_bytes(), b"moss editable fixture")
        self.assertEqual(snapshot(self.target), self.before)

    def test_oversized_http_body_is_rejected_before_writing_excess_bytes(self):
        class Response(io.BytesIO):
            status = 200
            headers = {"Content-Length": "5"}
        destination = self.root / "bounded.bin"
        with mock.patch.object(downloader.urllib.request, "urlopen",
                               return_value=Response(b"too much data")), \
                self.assertRaisesRegex(RuntimeError, "response exceeds expected bytes"):
            downloader.download("https://huggingface.co/fixture", destination,
                hashlib.sha256(b"12345").hexdigest().upper(), 5, max_attempts=1)
        self.assertFalse(destination.exists())
        self.assertLessEqual(destination.with_suffix(".bin.part").stat().st_size, 5)


NATIVE_PROBE = r'''
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
class ModelUpdateProbe {
    static int Main(string[] args) {
        try {
            if (args[0] == "protocol") {
                var manifest = UpdateProtocol.Read(File.ReadAllText(args[1]));
                UpdateProtocol.ValidateForInstallation(manifest, "8.0.3");
                return 0;
            }
            using (var cancellation = new CancellationTokenSource()) {
                int child = 0;
                try {
                    var result = RuntimeBundleInstaller.RunPython(args[1], args[2],
                        new[] { "-u", "-c", args[3] }, line => {
                            if (line.StartsWith("PID=")) {
                                child = Int32.Parse(line.Substring(4));
                                cancellation.CancelAfter(100);
                            }
                        }, cancellation.Token);
                    return args[0] == "success" && (string)result["status"] == "ok" ? 0 : 11;
                } catch (OperationCanceledException) {
                    if (args[0] != "cancel" || child == 0) return 12;
                    try {
                        using (var process = Process.GetProcessById(child))
                            if (!process.HasExited) return 13;
                    } catch (ArgumentException) {}
                    return 0;
                }
            }
        } catch (Exception error) {
            Console.Error.WriteLine(error);
            return 1;
        }
    }
}
'''


@unittest.skipUnless(CSC.is_file(), "Windows .NET compiler required")
class NativeModelPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="lakis-model-native-")
        cls.root = Path(cls.temp.name)
        probe = cls.root / "probe.cs"
        probe.write_text(NATIVE_PROBE, encoding="utf-8")
        cls.exe = cls.root / "probe.exe"
        result = subprocess.run([
            str(CSC), "/nologo", "/target:exe", "/out:" + str(cls.exe),
            "/r:System.Web.Extensions.dll", str(ROOT / "installer/UpdateProtocol.cs"),
            str(ROOT / "installer/RuntimeBundleInstaller.cs"), str(probe),
        ], capture_output=True, timeout=60)
        if result.returncode:
            cls.temp.cleanup()
            raise RuntimeError(result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def probe(self, *args):
        return subprocess.run([str(self.exe), *map(str, args)], capture_output=True, timeout=15)

    def test_python_preparation_success_keeps_json_result(self):
        result = self.probe("success", sys.executable, self.root,
                            'print(\'{"status":"ok"}\')')
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_cancel_stops_owned_child_even_without_output_and_keeps_partial_data(self):
        partial = self.root / "model.part"
        script = ("import os, time; from pathlib import Path; "
                  f"Path({str(partial)!r}).write_bytes(b'keep for resume'); "
                  "print('PID=' + str(os.getpid()), flush=True); time.sleep(60)")
        result = self.probe("cancel", sys.executable, self.root, script)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(partial.read_bytes(), b"keep for resume")

    def test_native_protocol_requires_runtime_update_and_new_engine(self):
        manifest = {
            "schema": 2, "kind": "runtime-update", "version": "8.1.0",
            "minimum_version": "8.0.0", "minimum_updater_version": "8.1.0",
            "files": [], "delete": [],
            "runtime_bundle": {"schema": 2, "product": "LAKIS", "version": "8.1.0",
                               "manifest_sha256": "A" * 64},
        }
        path = self.root / "update.json"
        path.write_text(json.dumps(manifest))
        result = self.probe("protocol", path)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        manifest["minimum_updater_version"] = "8.0.0"
        path.write_text(json.dumps(manifest))
        self.assertNotEqual(self.probe("protocol", path).returncode, 0)
        manifest.update(kind="file-patch", runtime_bundle=None, files=[
            {"path": "VERSION", "url": "https://github.com/fixture", "sha256": "A" * 64}])
        path.write_text(json.dumps(manifest))
        self.assertNotEqual(self.probe("protocol", path).returncode, 0)


if __name__ == "__main__":
    unittest.main()
