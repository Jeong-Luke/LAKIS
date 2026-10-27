"""Official-model routing and additive transactions in disposable installations."""
import copy
import hashlib
from pathlib import Path
from unittest import mock
import unittest

import test_runtime_patch as component_tests
import runtime_install as install
import runtime_manifest as contract
import runtime_patch as patcher
import runtime_transition as transition
import runtime_update as update
import test_runtime_update as routing_tests


class PoseModelDownloadTests(unittest.TestCase):
    def setUp(self):
        self.fixture = component_tests.RuntimeComponentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.catalog = copy.deepcopy(contract.POSE_MODELS)
        self.files = {}
        for index, (relative, spec) in enumerate(self.catalog.items()):
            source = self.fixture.root / f"publisher-{index}.bin"
            data = f"official-fixture-{index}".encode()
            source.write_bytes(data)
            spec.update(size=len(data), sha256=hashlib.sha256(data).hexdigest().upper())
            self.files[relative] = source
        catalog = mock.patch.object(contract, "POSE_MODELS", self.catalog)
        catalog.start()
        self.addCleanup(catalog.stop)
        self.calls = []

    def download(self, url, destination, digest, size, *, display_name):
        self.calls.append((url, digest, size, display_name))
        relative, spec = next((key, value) for key, value in self.catalog.items()
                              if value["url"] == url)
        self.assertEqual((digest, size, display_name),
                         (spec["sha256"], spec["size"], spec["name"]))
        return self.files[relative]

    def apply(self, files):
        return patcher.activate(self.fixture.candidate, self.fixture.target,
                                self.fixture.manifest_hash, "8.0.0", model_files=files)

    def test_fresh_defaults_use_the_same_official_pins(self):
        workflow = self.fixture.candidate / "ComfyUI/LAKIS/workflows/LAKIS_custom_v7.4_editable.json"
        workflow.write_bytes(b"{}")
        with mock.patch.object(install, "download", side_effect=self.download), \
                mock.patch.object(install, "create_default_input_image"):
            seed = install.prepare_default_data(
                self.fixture.candidate, {"models": []}, self.fixture.root / "cache", "cmd",
            )
        self.assertEqual(len(self.calls), 2)
        for relative, source in self.files.items():
            self.assertEqual((seed / relative).read_bytes(), source.read_bytes())
        self.fixture.assert_original()

    def test_update_downloads_adds_and_rollback_preserves_models(self):
        with mock.patch.object(install, "download", side_effect=self.download):
            files = install.prepare_pose_models(self.fixture.root / "cache", self.fixture.target)
        self.fixture.assert_original()  # Preparation never touches the installation.
        result = self.apply(files)
        self.assertEqual(set(result["added_pose_models"]), set(self.catalog))
        for relative, source in files.items():
            self.assertEqual((self.fixture.target / relative).read_bytes(), source.read_bytes())
        self.assertEqual(self.fixture.model.stat().st_ino, self.fixture.model_identity)
        with mock.patch.object(transition, "assert_idle"):
            transition.recover(self.fixture.target, self.fixture.candidate / "python_embeded/python.exe")
        self.assertEqual((self.fixture.target / "VERSION").read_text(), "7.5.4")
        for relative, source in files.items():
            self.assertEqual((self.fixture.target / relative).read_bytes(), source.read_bytes())
        for relative, data in self.fixture.original.items():
            self.assertEqual((self.fixture.target / relative).read_bytes(), data)

    def test_existing_valid_models_are_reused_without_download_or_replacement(self):
        identities = {}
        for relative, source in self.files.items():
            destination = self.fixture.target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
            identities[relative] = destination.stat().st_ino
        with mock.patch.object(install, "download") as download:
            files = install.prepare_pose_models(self.fixture.root / "cache", self.fixture.target)
        download.assert_not_called()
        self.assertEqual(self.apply(files)["added_pose_models"], [])
        for relative, identity in identities.items():
            self.assertEqual((self.fixture.target / relative).stat().st_ino, identity)

    def test_existing_conflict_is_preserved_and_blocks_update(self):
        relative = next(iter(self.catalog))
        destination = self.fixture.target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"user-owned-different-model")
        before = self.fixture.snapshot(self.fixture.target)
        with mock.patch.object(install, "download") as download, \
                self.assertRaisesRegex(ValueError, "기존 모델"):
            install.prepare_pose_models(self.fixture.root / "cache", self.fixture.target)
        download.assert_not_called()
        with self.assertRaisesRegex(ValueError, "기존 모델"):
            self.apply(self.files)
        self.assertEqual(self.fixture.snapshot(self.fixture.target), before)

    def test_changed_download_and_unlisted_target_cannot_modify_installation(self):
        bad = dict(self.files)
        bad["ComfyUI/models/other.safetensors"] = next(iter(self.files.values()))
        with self.assertRaisesRegex(ValueError, "download set"):
            self.apply(bad)
        self.fixture.assert_original()
        next(iter(self.files.values())).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "verification"):
            self.apply(self.files)
        self.fixture.assert_original()

    def test_file_created_during_preparation_is_never_overwritten(self):
        relative = next(iter(self.catalog))
        destination = self.fixture.target / relative
        original_stage = patcher._stage_component

        def race(source, stage):
            original_stage(source, stage)
            if str(source).replace("\\", "/").endswith(relative):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"concurrent-user-file")

        with mock.patch.object(patcher, "_stage_component", side_effect=race), \
                self.assertRaises(RuntimeError):
            self.apply(self.files)
        self.assertEqual(destination.read_bytes(), b"concurrent-user-file")
        self.assertEqual((self.fixture.target / "VERSION").read_text(), "7.5.4")
        self.assertEqual(self.fixture.model.stat().st_ino, self.fixture.model_identity)

    def test_repair_adds_missing_models_in_stage_without_changing_existing_data(self):
        (self.fixture.target / "VERSION").write_text("8.0.0")
        with mock.patch.object(transition, "assert_idle"), \
                mock.patch.object(transition, "check_runtime", return_value={}):
            result = transition.activate(
                self.fixture.candidate, self.fixture.target, self.fixture.manifest_hash,
                "8.0.0", "repair", model_files=self.files,
            )
        self.assertEqual(result["status"], "complete")
        for relative, source in self.files.items():
            self.assertEqual((self.fixture.target / relative).read_bytes(), source.read_bytes())
        for relative, data in self.fixture.original.items():
            if relative.startswith(("ComfyUI/models/", "ComfyUI/input/", "ComfyUI/output/")):
                self.assertEqual((self.fixture.target / relative).read_bytes(), data)

    def test_updater_preparation_requests_models_and_failure_does_not_activate(self):
        routing = routing_tests.RuntimeUpdateEntryTests()
        routing.setUp()
        self.addCleanup(routing.doCleanups)
        with mock.patch.object(update, "prepare_bundle", return_value=routing.fixture.candidate), \
                mock.patch.object(update, "prepare_pose_models", side_effect=RuntimeError("download failed")), \
                mock.patch.object(update, "activate") as activate, \
                self.assertRaisesRegex(RuntimeError, "download failed"):
            routing.run_update(prepare_only=True)
        activate.assert_not_called()
        routing.fixture.assert_original()


if __name__ == "__main__":
    unittest.main()
