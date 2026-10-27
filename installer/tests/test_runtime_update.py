"""Exercise schema-2 routing against real component transactions in a fixture."""
import copy
import hashlib
from unittest import mock
import unittest

import test_runtime_patch as component_tests
import runtime_update as update


class RuntimeUpdateEntryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = component_tests.RuntimeComponentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        # Publisher transfer/addition is exercised by test_pose_model_downloads.
        models = mock.patch.object(update, "prepare_pose_models", return_value=None)
        models.start()
        self.addCleanup(models.stop)
        self.manifest = {
            "schema": 2, "kind": "runtime-update", "version": "8.0.0",
            "minimum_version": "7.5.4", "minimum_updater_version": "8.0.0",
            "files": [], "delete": [],
            "runtime_bundle": {
                "schema": 2, "product": "LAKIS", "version": "8.0.0",
                "comfyui_version": "0.42.0", "name": "runtime.zip",
                "bytes": 1, "files": 1, "sha256": hashlib.sha256(b"x").hexdigest(),
                "manifest_sha256": self.fixture.manifest_hash,
                "parts": [{
                    "name": "runtime.zip.part001", "bytes": 1,
                    "sha256": hashlib.sha256(b"x").hexdigest(),
                    "url": "https://github.com/Jeong-Luke/LAKIS/releases/download/v8.0.0/runtime.zip.part001",
                }],
            },
        }

    def run_update(self, **options):
        return update.run(self.manifest, self.fixture.target, self.fixture.root / "cache", **options)

    def test_prepare_rejects_legacy_installation_before_download(self):
        self.manifest["minimum_version"] = "7.5.4.1"
        for current in ("7.5.3", "7.5.4", "7.5.4.0"):
            with self.subTest(current=current):
                (self.fixture.target / "VERSION").write_text(current)
                with mock.patch.object(update, "prepare_bundle") as prepare:
                    with self.assertRaisesRegex(ValueError, "bridge"):
                        self.run_update(prepare_only=True)
                    prepare.assert_not_called()

    def test_bridge_revision_prepares_without_changing_the_installation(self):
        (self.fixture.target / "VERSION").write_text("7.5.4.1")
        self.manifest["minimum_version"] = "7.5.4.1"
        before = self.fixture.snapshot(self.fixture.target)
        with mock.patch.object(update, "prepare_bundle", return_value=self.fixture.candidate):
            result = self.run_update(prepare_only=True)
        self.assertEqual(result, {"status": "prepared", "candidate": str(self.fixture.candidate)})
        self.assertEqual(self.fixture.snapshot(self.fixture.target), before)
        self.assertEqual(self.fixture.model.stat().st_ino, self.fixture.model_identity)

    def test_bridge_revision_updates_and_rolls_back_to_its_exact_version(self):
        (self.fixture.target / "VERSION").write_text("7.5.4.1")
        self.manifest["minimum_version"] = "7.5.4.1"
        before = self.fixture.snapshot(self.fixture.target)
        result = self.run_update(prepared_root=self.fixture.candidate)
        self.assertEqual(result["status"], "complete")
        self.assertEqual((self.fixture.target / "VERSION").read_text(), "8.0.0")
        with mock.patch("runtime_transition.assert_idle"):
            result = self.run_update(prepared_root=self.fixture.candidate, rollback=True)
        self.assertEqual(result["status"], "rolled-back")
        self.assertEqual(self.fixture.snapshot(self.fixture.target), before)
        self.assertEqual(self.fixture.model.stat().st_ino, self.fixture.model_identity)

    def test_equivalent_newer_and_malformed_versions_cannot_start_an_update(self):
        for current in ("8.0.0", "8.0.0.0", "8.0.0.1", "8.1.0", "7.5.4.1.invalid"):
            with self.subTest(current=current):
                (self.fixture.target / "VERSION").write_text(current)
                before = self.fixture.snapshot(self.fixture.target)
                with mock.patch.object(update, "prepare_bundle") as prepare:
                    with self.assertRaises(ValueError):
                        self.run_update(prepare_only=True)
                    prepare.assert_not_called()
                self.assertEqual(self.fixture.snapshot(self.fixture.target), before)

    def test_zero_revision_is_equivalent_for_repair_version_comparison(self):
        (self.fixture.target / "VERSION").write_text("8.0.0.0")
        self.assertTrue(update._assert_original(self.fixture.target, "8.0.0", "repair"))
        (self.fixture.target / "VERSION").write_text("8.0.0.1")
        with self.assertRaises(ValueError):
            update._assert_original(self.fixture.target, "8.0.0", "repair")

    def test_runtime_release_version_still_requires_three_components(self):
        self.manifest["version"] = "8.0.0.1"
        self.manifest["runtime_bundle"]["version"] = "8.0.0.1"
        with self.assertRaises(ValueError):
            self.run_update(prepared_root=self.fixture.candidate)
        self.fixture.assert_original()

    def test_invalid_operation_or_requirement_cannot_change_installation(self):
        for field, value in (("schema", 1), ("kind", "file-patch"),
                             ("minimum_updater_version", "8.0.1"),
                             ("minimum_version", "7.5.3"), ("delete", ["LAKIS.exe"])):
            changed = copy.deepcopy(self.manifest)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                update.run(changed, self.fixture.target, self.fixture.root / "cache",
                           prepared_root=self.fixture.candidate)
            self.fixture.assert_original()

    def test_apply_and_explicit_recovery_preserve_user_files(self):
        result = self.run_update(prepared_root=self.fixture.candidate)
        self.assertEqual(result["status"], "complete")
        output = self.fixture.target / "ComfyUI/output/new-image.bin"
        output.write_bytes(b"new-output")
        with mock.patch("runtime_transition.assert_idle"):
            result = self.run_update(prepared_root=self.fixture.candidate, rollback=True)
        self.assertEqual(result["status"], "rolled-back")
        self.assertEqual(output.read_bytes(), b"new-output")
        self.assertEqual((self.fixture.target / "VERSION").read_text(), "7.5.4")
        self.assertEqual(self.fixture.model.stat().st_ino, self.fixture.model_identity)

    def test_health_failure_rolls_back_instead_of_marking_complete(self):
        with mock.patch("runtime_patch.check_runtime", side_effect=RuntimeError("health failed")):
            with self.assertRaisesRegex(RuntimeError, "health failed"):
                self.run_update(prepared_root=self.fixture.candidate)
        self.fixture.assert_original()

    def test_rollback_refuses_unrelated_manifest(self):
        self.run_update(prepared_root=self.fixture.candidate)
        self.manifest["runtime_bundle"]["manifest_sha256"] = "B" * 64
        with self.assertRaisesRegex(ValueError, "journal"):
            self.run_update(prepared_root=self.fixture.candidate, rollback=True)
        self.assertEqual((self.fixture.target / "VERSION").read_text(), "8.0.0")


if __name__ == "__main__":
    unittest.main()
