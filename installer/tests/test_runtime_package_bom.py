"""Keep the package BOM tied to the metadata actually included in its archive."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from benchmark_native_runtime import NATIVE_NAMES, package
import runtime_manifest as contract


class RuntimePackageBomTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="runtime-bom-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.binaries = self.root / "binaries"
        self.work = self.root / "package"
        self.binaries.mkdir()
        self.work.mkdir()
        self.manifest = {
            "schema": 1, "product": "LAKIS", "version": "8.0.0",
            "runtime": {"packages": {"removed-package": "9.9", "Actual_Package": "0.1"}},
            "files": [],
        }
        for name in contract.REQUIRED_FILES:
            self.add_file(name, ("old-" + name).encode())
        for name in NATIVE_NAMES:
            (self.binaries / name).write_bytes(("new-" + name).encode())
        self.metadata = "python_embeded/Lib/site-packages/actual_package-1.2.3.dist-info/METADATA"
        self.add_file(self.metadata, b"Metadata-Version: 2.4\nName: Actual_Package\nVersion: 1.2.3\n\n")
        self.add_file(
            "python_embeded/Lib/site-packages/another-4.5.6.dist-info/METADATA",
            b"Metadata-Version: 2.4\nName: Another.Name\nVersion: 4.5.6\n\n",
        )

    def add_file(self, relative, data):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.manifest["files"].append({
            "path": relative, "size": len(data), "sha256": hashlib.sha256(data).hexdigest().upper(),
        })

    def test_bom_uses_verified_metadata_without_changing_the_original_manifest(self):
        before = copy.deepcopy(self.manifest)
        _, bundle = package(self.source, self.manifest, self.binaries, self.work)
        with zipfile.ZipFile(self.work / bundle["name"]) as archive:
            raw = archive.read(contract.MANIFEST_NAME)
            actual = json.loads(raw)
            self.assertEqual(actual["runtime"]["packages"], {
                "Actual_Package": "1.2.3", "Another.Name": "4.5.6",
            })
            self.assertEqual(hashlib.sha256(raw).hexdigest().upper(), bundle["manifest_sha256"])
            for name in NATIVE_NAMES:
                self.assertEqual(archive.read(name), ("new-" + name).encode())
                self.assertEqual((self.source / name).read_bytes(), ("old-" + name).encode())
        self.assertEqual(self.manifest, before)

    def test_changed_metadata_cannot_produce_a_completed_package(self):
        (self.source / self.metadata).write_bytes(b"Name: Unexpected\nVersion: 9.0\n\n")
        with self.assertRaisesRegex(RuntimeError, "runtime input changed"):
            package(self.source, self.manifest, self.binaries, self.work)
        self.assertFalse((self.work / "assets").exists())

    def test_hotfix_version_is_consistent_in_bundle_archive_and_installed_marker(self):
        self.manifest["version"] = "8.0.1"
        pins = {
            name: self.overlay_file(name, ("hotfix-" + name).encode())
            for name in ("LAKIS_Desktop.exe", "LAKIS_Model_Importer.exe", "Uninstall_LAKIS.exe")
        }
        _, bundle = package(self.source, self.manifest, self.binaries, self.work,
                            application_files=pins)
        self.assertEqual(bundle["version"], "8.0.1")
        self.assertEqual(bundle["name"], "LAKIS_Runtime_8.0.1.zip")
        for part in bundle["parts"]:
            self.assertEqual(part["url"], "https://github.com/Jeong-Luke/LAKIS/releases/download/v8.0.1/" + part["name"])
        with zipfile.ZipFile(self.work / bundle["name"]) as archive:
            self.assertEqual(archive.read("VERSION"), b"8.0.1")
            for name, pin in pins.items():
                self.assertEqual(archive.read(name), pin["source"].read_bytes())
            manifest = json.loads(archive.read(contract.MANIFEST_NAME))
            self.assertEqual(manifest["version"], "8.0.1")
            marker = next(row for row in manifest["files"] if row["path"] == "VERSION")
            self.assertEqual(marker["sha256"], hashlib.sha256(b"8.0.1").hexdigest().upper())
        self.assertEqual((self.source / "VERSION").read_bytes(), b"old-VERSION")

    def test_vendored_metadata_is_preserved_but_not_counted_as_an_installed_distribution(self):
        vendored = {
            "python_embeded/Lib/site-packages/setuptools/_vendor/actual_package-0.9.dist-info/METADATA":
                b"Metadata-Version: 2.4\nName: Actual_Package\nVersion: 0.9\n\n",
            "python_embeded/Lib/site-packages/setuptools/_vendor/only_vendored-2.0.dist-info/METADATA":
                b"Metadata-Version: 2.4\nName: Only-Vendored\nVersion: 2.0\n\n",
        }
        for name, data in vendored.items():
            self.add_file(name, data)
        _, bundle = package(self.source, self.manifest, self.binaries, self.work)
        with zipfile.ZipFile(self.work / bundle["name"]) as archive:
            actual = json.loads(archive.read(contract.MANIFEST_NAME))
            self.assertEqual(actual["runtime"]["packages"], {
                "Actual_Package": "1.2.3", "Another.Name": "4.5.6",
            })
            rows = {row["path"]: row for row in actual["files"]}
            for name, data in vendored.items():
                self.assertEqual(archive.read(name), data)
                self.assertEqual(rows[name]["sha256"], hashlib.sha256(data).hexdigest().upper())
                self.assertEqual((self.source / name).read_bytes(), data)

    def overlay_file(self, relative, data):
        source = self.root / "overlay" / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(data)
        return {"source": source, "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest().upper()}

    def test_pinned_overlay_adds_missing_licenses_and_replaces_ui_without_source_writes(self):
        license_name = "third_party_licenses/NVIDIA-CUDA-13.0.0-EULA.md"
        self.manifest["files"] = [
            row for row in self.manifest["files"] if row["path"] != license_name
        ]
        (self.source / license_name).unlink()
        ui_name = "ComfyUI/LAKIS/external_ui/scene-controls.js"
        pins = {
            license_name: self.overlay_file(license_name, b"publisher licence fixture\n"),
            ui_name: self.overlay_file(ui_name, b"current approved scene editor"),
            "THIRD_PARTY_NOTICES.md": self.overlay_file("THIRD_PARTY_NOTICES.md", b"current notices"),
        }
        _, bundle = package(self.source, self.manifest, self.binaries, self.work,
                            application_files=pins)
        with zipfile.ZipFile(self.work / bundle["name"]) as archive:
            for name, pin in pins.items():
                self.assertEqual(archive.read(name), pin["source"].read_bytes())
            rows = {row["path"]: row for row in json.loads(
                archive.read(contract.MANIFEST_NAME))["files"]}
            self.assertEqual(rows[license_name]["sha256"], pins[license_name]["sha256"])
        self.assertFalse((self.source / license_name).exists())
        self.assertEqual((self.source / "THIRD_PARTY_NOTICES.md").read_bytes(),
                         b"old-THIRD_PARTY_NOTICES.md")

    def test_overlay_cannot_change_user_data_core_or_generated_files(self):
        pin = self.overlay_file("fixture.txt", b"unchanged source")
        for name in (
            "ComfyUI/models/controlnet/user.safetensors", "ComfyUI/user/settings.json",
            "ComfyUI/main.py", "../outside.txt", "LAKIS_Updater.exe",
            "ComfyUI/LAKIS/external_ui/__pycache__/fixture.pyc",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                package(self.source, self.manifest, self.binaries, self.work,
                        application_files={name: pin})
        self.assertFalse((self.work / "LAKIS_Runtime_8.0.0.zip").exists())

    def test_changed_overlay_and_missing_notice_fail_before_archive_creation(self):
        name = "THIRD_PARTY_NOTICES.md"
        pin = self.overlay_file(name, b"approved")
        pin["source"].write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "application source changed"):
            package(self.source, self.manifest, self.binaries, self.work,
                    application_files={name: pin})
        self.manifest["files"] = [
            row for row in self.manifest["files"]
            if row["path"] != "third_party_licenses/NVIDIA-CUDA-13.0.0-EULA.md"
        ]
        with self.assertRaisesRegex(ValueError, "incomplete runtime"):
            package(self.source, self.manifest, self.binaries, self.work)
        self.assertFalse((self.work / "LAKIS_Runtime_8.0.0.zip").exists())

    def test_equivalent_distribution_names_are_not_counted_twice(self):
        self.add_file(
            "python_embeded/Lib/site-packages/duplicate-1.2.3.dist-info/METADATA",
            b"Metadata-Version: 2.4\nName: actual-package\nVersion: 1.2.3\n\n",
        )
        with self.assertRaisesRegex(RuntimeError, "duplicate installed distribution"):
            package(self.source, self.manifest, self.binaries, self.work)
        self.assertFalse((self.work / "assets").exists())


if __name__ == "__main__":
    unittest.main()
