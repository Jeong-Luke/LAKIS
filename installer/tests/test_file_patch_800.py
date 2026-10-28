"""Focused application-patch checks using the published 8.0.0 updater."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from test_updater_bridge import bridge, server


PATCH_NAMES = (
    "index.html", "scene-controls.css", "scene-controls.js", "scene_controls.py",
    "serve_ui.py", "app.js", "diagnostic-packet.js", "generation-diagnostics.js",
)
EXPECTED = {}
for _name in PATCH_NAMES:
    _source = (bridge.ROOT / "src/external_ui" / _name).read_bytes().replace(b"\r\n", b"\n")
    EXPECTED[_name] = (len(_source), hashlib.sha256(_source).hexdigest().upper())
PREFIX = "ComfyUI/LAKIS/external_ui/"
PINNED_RUNTIME_URL = (
    "https://github.com/Jeong-Luke/LAKIS/releases/download/v8.0.0/update-v3-latest.json"
)


class FilePatch800Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifacts = Path(os.environ["LAKIS_HOTFIX_ARTIFACTS"])
        cls.baseline = Path(os.environ["LAKIS_800_BASELINE_ASSETS"])
        cls.bridge_output = Path(os.environ["LAKIS_PINNED_BRIDGE"])
        cls.updater = Path(os.environ["LAKIS_800_UPDATER"])
        expected = "f1812b96534b1a940999a7ce7fa085eeac505ec18cf7271cb671ddbadf6b11e7"
        if bridge.digest(cls.updater) != expected:
            raise ValueError("published 8.0.0 updater hash mismatch")
        cls.work = Path(tempfile.mkdtemp(prefix="file-patch-800-"))
        cls.probe_path = cls.work / "FilePatchProbe.exe"
        bridge.compile_native(cls.probe_path, [
            bridge.ROOT / "installer/LAKIS_Updater.cs",
            bridge.ROOT / "installer/LAKIS_Launcher.cs",
            Path(__file__).with_name("UpdaterBridgeProbe.cs"),
        ], main="UpdaterBridgeProbe")
        cls.manifest = json.loads(
            (cls.artifacts / "update-v3-latest.json").read_text(encoding="utf-8-sig"))

    def probe(self, *args, success=True):
        result = subprocess.run([str(self.probe_path), *map(str, args)],
                                capture_output=True, timeout=45)
        diagnostic = result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")
        if success:
            self.assertEqual(result.returncode, 0, diagnostic)
        else:
            self.assertNotEqual(result.returncode, 0, diagnostic)
            self.assertTrue(result.stderr.startswith(b"InvalidDataException:"), diagnostic)
        return result

    def fixture(self, version="8.0.0"):
        root = Path(tempfile.mkdtemp(prefix="target-", dir=self.work))
        (root / "VERSION").write_bytes(version.encode("ascii"))
        (root / "LAKIS.exe").write_bytes(b"fixture-launcher-not-executed")
        with zipfile.ZipFile(self.baseline / "LAKIS_RepairPack.zip") as archive:
            for name in EXPECTED:
                if PREFIX + name not in archive.namelist():
                    continue
                target = root / PREFIX / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(PREFIX + name))
        protected = {
            "ComfyUI/models/fixture.bin": b"locked-original-model",
            "ComfyUI/user/settings.json": b'{"retain":true}',
            "ComfyUI/user/default/workflows/my-workflow.json": b'{"user":"workflow"}',
            "ComfyUI/output/original.webp": b"original-user-image",
            "ComfyUI/input/original.png": b"original-user-input",
            ".lakis/license.json": b'{"fixture":"license"}',
            "RUNTIME_SHA256SUMS.json": b'{"version":"8.0.0","fixture":true}',
        }
        for relative, data in protected.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return root, protected

    def routes(self):
        manifest = json.loads(json.dumps(self.manifest))
        routes = {}
        for row in manifest["files"]:
            name = Path(row["path"]).name
            routes["/" + name] = (self.artifacts / name).read_bytes()
        return manifest, routes

    def test_manifest_and_exact_payload(self):
        self.assertEqual(self.manifest["schema"], 2)
        self.assertEqual(self.manifest["kind"], "file-patch")
        self.assertEqual(self.manifest["version"], "8.0.1")
        self.assertEqual(self.manifest["minimum_version"], "8.0.0")
        self.assertEqual(self.manifest["minimum_updater_version"], "8.0.0")
        self.assertEqual(self.manifest["delete"], [])
        self.assertNotIn("runtime_bundle", self.manifest)
        self.assertEqual(len(self.manifest["files"]), len(EXPECTED))
        self.assertEqual({row["path"] for row in self.manifest["files"]},
                         {PREFIX + name for name in EXPECTED})
        for row in self.manifest["files"]:
            name = Path(row["path"]).name
            size, expected_hash = EXPECTED[name]
            data = (self.artifacts / name).read_bytes()
            self.assertEqual(len(data), size)
            self.assertEqual(hashlib.sha256(data).hexdigest().upper(), expected_hash)
            self.assertEqual(row["sha256"].upper(), expected_hash)
            self.assertEqual(row["url"],
                             "https://github.com/Jeong-Luke/LAKIS/releases/download/v8.0.1/" + name)

    def test_repair_pack_preserves_baseline_except_patch(self):
        with zipfile.ZipFile(self.baseline / "LAKIS_RepairPack.zip") as original, \
                zipfile.ZipFile(self.artifacts / "LAKIS_RepairPack.zip") as updated:
            expected_paths = set(original.namelist()) | {PREFIX + name for name in EXPECTED}
            self.assertEqual(set(updated.namelist()), expected_paths)
            self.assertEqual(len(updated.namelist()), len(expected_paths))
            for entry in original.infolist():
                expected = (b"8.0.1" if entry.filename == "VERSION"
                            else (self.artifacts / Path(entry.filename).name).read_bytes()
                            if entry.filename in {PREFIX + name for name in EXPECTED}
                            else original.read(entry))
                self.assertEqual(updated.read(entry.filename), expected, entry.filename)
            for name in EXPECTED:
                self.assertEqual(updated.read(PREFIX + name), (self.artifacts / name).read_bytes())
        original_layout = json.loads(
            (self.baseline / "release-layout.json").read_text(encoding="utf-8-sig"))
        updated_layout = json.loads(
            (self.artifacts / "release-layout.json").read_text(encoding="utf-8-sig"))
        original_layout["version"] = "8.0.1"
        expected_rows = {row["path"]: row for row in original_layout.pop("files")}
        actual_rows = {row["path"]: row for row in updated_layout.pop("files")}
        for name, (size, _) in EXPECTED.items():
            expected_rows.setdefault(PREFIX + name, {"path": PREFIX + name})
            expected_rows[PREFIX + name]["size"] = size
        self.assertEqual(actual_rows, expected_rows)
        self.assertEqual(updated_layout, original_layout)

    def test_published_updater_applies_patch_without_touching_user_data(self):
        root, protected = self.fixture()
        manifest, routes = self.routes()
        with server(routes) as (base, requests):
            for row in manifest["files"]:
                row["url"] = base + "/" + Path(row["path"]).name
            document = json.dumps(manifest).encode()
            routes["/manifest.json"] = document
            path = root / "fixture-manifest.json"
            path.write_bytes(document)
            loaded = self.probe("legacy-read", root, base + "/manifest.json", self.updater)
            self.assertEqual(json.loads(loaded.stdout)["version"], "8.0.1")
            self.probe("legacy-apply", root, base + "/manifest.json", self.updater, path)
            self.assertEqual((root / "VERSION").read_bytes(), b"8.0.1")
            for name, (_, digest) in EXPECTED.items():
                self.assertEqual(bridge.digest(root / PREFIX / name).upper(), digest)
            for relative, data in protected.items():
                self.assertEqual((root / relative).read_bytes(), data, relative)
            self.assertEqual(set(requests), {"/manifest.json", *{"/" + name for name in EXPECTED}})
            backups = list((root / ".lakis/rollback").iterdir())
            self.assertEqual(len(backups), 1)
            backed_up = {file.relative_to(backups[0]).as_posix()
                         for file in backups[0].rglob("*") if file.is_file()}
            with zipfile.ZipFile(self.baseline / "LAKIS_RepairPack.zip") as original:
                expected_backups = set(original.namelist()) & {PREFIX + name for name in EXPECTED}
            self.assertEqual(backed_up, expected_backups)
            self.assertFalse((root / "LAKIS_Desktop.exe").exists())

    def test_published_updater_rejects_pre_runtime_installation(self):
        root, _ = self.fixture("7.5.4.1")
        with server({"/manifest.json": json.dumps(self.manifest).encode()}) as (base, _):
            self.probe("legacy-read", root, base + "/manifest.json",
                       self.updater, success=False)

    def test_pinned_bridge_does_not_use_the_hotfix_channel(self):
        for name in ("LAKIS_RuntimeBridge_Launcher.exe", "LAKIS_RuntimeBridge_Updater.exe"):
            result = self.probe("assembly-defaults", self.bridge_output / name)
            self.assertEqual(result.stdout.decode().strip(), PINNED_RUNTIME_URL)
        self.assertEqual(
            bridge.digest(self.bridge_output / "LAKIS_RuntimeBridge_Updater.exe"),
            bridge.digest(self.bridge_output / "LAKIS_RuntimeBridge_Patcher.exe"))
        manifest = json.loads(
            (self.bridge_output / "update-v2-latest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "7.5.4.1")
        self.assertEqual(manifest["minimum_version"], "7.5.4")
        self.assertEqual(manifest["minimum_updater_version"], "7.5.4")
        self.assertEqual({row["path"] for row in manifest["files"]},
                         {"LAKIS.exe", "LAKIS_Updater.exe", "LAKIS_Patcher.exe"})
        for row in manifest["files"]:
            asset = row["url"].rsplit("/", 1)[-1]
            self.assertEqual(row["sha256"].lower(), bridge.digest(self.bridge_output / asset))

    def test_normal_engine_keeps_the_existing_v3_channel(self):
        expected = "|".join([
            "https://raw.githubusercontent.com/Jeong-Luke/LAKIS/main/manifests/update-v3-latest.json",
            "https://cdn.jsdelivr.net/gh/Jeong-Luke/LAKIS@main/manifests/update-v3-latest.json",
        ])
        self.assertEqual(self.probe("defaults").stdout.decode().splitlines(), [expected, expected])


if __name__ == "__main__":
    unittest.main()
